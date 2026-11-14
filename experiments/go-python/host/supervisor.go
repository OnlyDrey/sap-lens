// Package main is the Phase 0 proof of concept of a small application host: it starts one Python/FastAPI child, hands it a secret
// capability without exposing it on the command line or in the environment, verifies a strict health response, and stops it without orphans.
// It is not an HTTP proxy and holds no business logic.
package main

import (
	"bufio"
	"context"
	"crypto/rand"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"sync"
	"time"
)

// Exit codes of the host; documented in docs/experiments/go-python.
const (
	ExitOK            = 0
	ExitUsage         = 1
	ExitStartFailure  = 2
	ExitStartTimeout  = 3
	ExitBackendExited = 4
)

var (
	ErrStartTimeout = errors.New("backend did not become ready before the deadline")
	ErrBadHealth    = errors.New("backend returned an unexpected health response")
)

// ChildExitedError reports that the backend ended before it was ready or while it was supposed to run.
type ChildExitedError struct {
	Code int
	Tail string
}

func (e *ChildExitedError) Error() string {
	return fmt.Sprintf("backend exited with code %d: %s", e.Code, e.Tail)
}

// Config describes one supervised child. Env is the COMPLETE environment of the child: nothing is inherited implicitly.
type Config struct {
	Executable   string
	Args         []string
	Dir          string
	Env          []string
	StartTimeout time.Duration
	StopTimeout  time.Duration
	Log          io.Writer // redacted child output and host messages
}

// Handoff is the one-time message written to the child's standard input. It never appears in arguments, environment or logs.
type Handoff struct {
	Capability string `json:"capability"`
	InstanceID string `json:"instance_id"`
}

type listening struct {
	Event string `json:"event"`
	Port  int    `json:"port"`
	PID   int    `json:"pid"`
}

// Supervisor owns one child process.
type Supervisor struct {
	cfg      Config
	cmd      *exec.Cmd
	stdin    io.WriteCloser
	handoff  Handoff
	redactor *Redactor
	tail     *tailBuffer
	done     chan struct{}
	exitCode int
	stopOnce sync.Once
	stopErr  error
	Port     int
	PID      int
	cleanup  func() // platform job/process-group cleanup
}

func randomToken(n int) string {
	buffer := make([]byte, n)
	if _, err := rand.Read(buffer); err != nil {
		panic(err) // no secure randomness: never continue with a weak capability
	}
	return base64.RawURLEncoding.EncodeToString(buffer)
}

func randomHex(n int) string {
	buffer := make([]byte, n)
	if _, err := rand.Read(buffer); err != nil {
		panic(err)
	}
	return hex.EncodeToString(buffer)
}

// NewSupervisor creates fresh, unpredictable secrets for this launch.
func NewSupervisor(cfg Config) *Supervisor {
	if cfg.StartTimeout <= 0 {
		cfg.StartTimeout = 30 * time.Second
	}
	if cfg.StopTimeout <= 0 {
		cfg.StopTimeout = 8 * time.Second
	}
	if cfg.Log == nil {
		cfg.Log = io.Discard
	}
	handoff := Handoff{Capability: randomToken(32), InstanceID: randomHex(16)}
	return &Supervisor{cfg: cfg, handoff: handoff, redactor: NewRedactor(handoff.Capability, handoff.InstanceID), tail: &tailBuffer{max: 2048}, done: make(chan struct{})}
}

// Start spawns the child, hands over the capability, waits for the listening report and then for a validated health response.
// Any failure stops and reaps the child before the error is returned.
func (s *Supervisor) Start(ctx context.Context) (err error) {
	deadline, cancel := context.WithTimeout(ctx, s.cfg.StartTimeout)
	defer cancel()
	cmd := exec.Command(s.cfg.Executable, s.cfg.Args...)
	cmd.Dir = s.cfg.Dir
	cmd.Env = s.cfg.Env
	configureChild(cmd)
	stdin, err := cmd.StdinPipe()
	if err != nil {
		return fmt.Errorf("stdin pipe: %w", err)
	}
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return fmt.Errorf("stdout pipe: %w", err)
	}
	stderr, err := cmd.StderrPipe()
	if err != nil {
		return fmt.Errorf("stderr pipe: %w", err)
	}
	if err = cmd.Start(); err != nil {
		return fmt.Errorf("start backend: %w", err)
	}
	s.cmd, s.stdin, s.PID = cmd, stdin, cmd.Process.Pid
	s.cleanup = attachToJob(cmd)
	lines := make(chan string, 1)
	go s.pump(stdout, lines, true)
	go s.pump(stderr, nil, false)
	go func() {
		waitErr := cmd.Wait()
		s.exitCode = exitCodeOf(waitErr)
		close(s.done)
	}()
	defer func() {
		if err != nil {
			_ = s.stopNow()
		}
	}()
	payload, _ := json.Marshal(s.handoff)
	if _, err = stdin.Write(append(payload, '\n')); err != nil {
		return fmt.Errorf("hand over capability: %w", err)
	}
	select {
	case line := <-lines:
		var report listening
		if err = json.Unmarshal([]byte(line), &report); err != nil || report.Event != "listening" || report.Port < 1 || report.Port > 65535 {
			return fmt.Errorf("%w: invalid listening report", ErrBadHealth)
		}
		s.Port = report.Port
	case <-s.done:
		return &ChildExitedError{Code: s.exitCode, Tail: s.redactor.Redact(s.tail.String())}
	case <-deadline.Done():
		return ErrStartTimeout
	}
	err = WaitHealthy(deadline, s.Port, s.handoff.InstanceID, s.done, 40*time.Millisecond)
	if errors.Is(err, errChildGone) {
		return &ChildExitedError{Code: s.exitCode, Tail: s.redactor.Redact(s.tail.String())}
	}
	if errors.Is(err, context.DeadlineExceeded) {
		return ErrStartTimeout
	}
	return err
}

// pump forwards child output through the redactor; the first stdout line is also delivered as the listening report.
func (s *Supervisor) pump(reader io.Reader, first chan<- string, report bool) {
	scanner := bufio.NewScanner(reader)
	scanner.Buffer(make([]byte, 0, 4096), 64*1024)
	sent := false
	for scanner.Scan() {
		line := scanner.Text()
		if report && !sent && first != nil {
			sent = true
			first <- line
			continue
		}
		clean := s.redactor.Redact(line)
		s.tail.Write(clean + "\n")
		fmt.Fprintf(s.cfg.Log, "backend: %s\n", clean)
	}
}

// Done is closed when the child has exited and been reaped.
func (s *Supervisor) Done() <-chan struct{} { return s.done }

// ExitCode is valid after Done is closed.
func (s *Supervisor) ExitCode() int { return s.exitCode }

// Stop asks the backend to leave (a line on stdin), waits for StopTimeout, then forces it. Idempotent.
func (s *Supervisor) Stop() error {
	s.stopOnce.Do(func() { s.stopErr = s.stopGracefully() })
	return s.stopErr
}

func (s *Supervisor) stopGracefully() error {
	if s.cmd == nil {
		return nil
	}
	select {
	case <-s.done:
		s.releaseJob()
		return nil
	default:
	}
	_, _ = s.stdin.Write([]byte("stop\n"))
	_ = s.stdin.Close()
	select {
	case <-s.done:
		s.releaseJob()
		return nil
	case <-time.After(s.cfg.StopTimeout):
	}
	forced := killTree(s.cmd)
	select {
	case <-s.done:
	case <-time.After(5 * time.Second):
		s.releaseJob()
		return errors.New("backend could not be reaped after a forced stop")
	}
	s.releaseJob()
	if forced != nil {
		return fmt.Errorf("forced stop: %w", forced)
	}
	return ErrForcedStop
}

// ErrForcedStop is returned by Stop when the graceful request was not honoured in time and the child had to be killed.
var ErrForcedStop = errors.New("backend did not stop gracefully and was terminated")

func (s *Supervisor) stopNow() error {
	if s.cmd == nil {
		return nil
	}
	select {
	case <-s.done:
	default:
		_ = s.stdin.Close()
		_ = killTree(s.cmd)
		select {
		case <-s.done:
		case <-time.After(5 * time.Second):
		}
	}
	s.releaseJob()
	return nil
}

func (s *Supervisor) releaseJob() {
	if s.cleanup != nil {
		s.cleanup()
		s.cleanup = nil
	}
}

func exitCodeOf(err error) int {
	if err == nil {
		return 0
	}
	var exit *exec.ExitError
	if errors.As(err, &exit) {
		return exit.ExitCode()
	}
	return -1
}

// tailBuffer keeps the last bytes of redacted child output for startup diagnostics.
type tailBuffer struct {
	mu  sync.Mutex
	max int
	buf []byte
}

func (t *tailBuffer) Write(text string) {
	t.mu.Lock()
	defer t.mu.Unlock()
	t.buf = append(t.buf, text...)
	if len(t.buf) > t.max {
		t.buf = t.buf[len(t.buf)-t.max:]
	}
}

func (t *tailBuffer) String() string {
	t.mu.Lock()
	defer t.mu.Unlock()
	return string(t.buf)
}

var _ = os.Getpid
