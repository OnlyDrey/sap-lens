package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"strconv"
	"strings"
	"testing"
	"time"
)

// The tests re-execute the test binary as a fake backend (the standard TestHelperProcess pattern): no Python and no network beyond loopback.

func TestMain(m *testing.M) {
	if os.Getenv("GO_WANT_HELPER") != "" {
		helperBackend()
		return
	}
	os.Exit(m.Run())
}

// helperBackend behaves like poc_backend.py according to HELPER_MODE.
func helperBackend() {
	mode := os.Getenv("HELPER_MODE")
	switch mode {
	case "exit_immediately":
		fmt.Fprintln(os.Stderr, "boom before ready")
		os.Exit(7)
	case "silent":
		select {}
	}
	var handoff Handoff
	buffer := make([]byte, 4096)
	count, _ := os.Stdin.Read(buffer)
	_ = json.Unmarshal(buffer[:count], &handoff)
	listener, _ := net.Listen("tcp", "127.0.0.1:0")
	port := listener.Addr().(*net.TCPAddr).Port
	instance := handoff.InstanceID
	if mode == "wrong_instance" {
		instance = strings.Repeat("0", 32)
	}
	mux := http.NewServeMux()
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		switch mode {
		case "redirect":
			http.Redirect(w, r, "http://127.0.0.1:1/", http.StatusFound)
		case "foreign_app":
			fmt.Fprintf(w, `{"app":"other","instance_id":%q,"status":"ok"}`, instance)
		case "bad_status":
			fmt.Fprintf(w, `{"app":"sap-lens","instance_id":%q,"status":"broken"}`, instance)
		default:
			fmt.Fprintf(w, `{"app":"sap-lens","instance_id":%q,"status":"ok"}`, instance)
		}
	})
	go http.Serve(listener, mux)
	if mode == "leak" {
		fmt.Fprintln(os.Stdout, `{"event":"listening","port":`+strconv.Itoa(port)+`,"pid":1}`)
		fmt.Fprintln(os.Stderr, "debug capability="+handoff.Capability+" instance="+handoff.InstanceID)
	} else {
		fmt.Fprintln(os.Stdout, `{"event":"listening","port":`+strconv.Itoa(port)+`,"pid":`+strconv.Itoa(os.Getpid())+`}`)
	}
	if mode == "ignore_stop" {
		select {} // never honours the stop request: the host must force it
	}
	for { // graceful: any "stop" line or end of input
		line := make([]byte, 64)
		n, err := os.Stdin.Read(line)
		if err != nil || strings.Contains(string(line[:n]), "stop") {
			os.Exit(0)
		}
	}
}

// A child that ignores the request must be forced quickly; a cooperative child gets generous time even under the race detector.
func stopFor(mode string) time.Duration {
	if mode == "ignore_stop" {
		return 600 * time.Millisecond
	}
	return 4 * time.Second
}

func fake(t *testing.T, mode string, timeout time.Duration) (*Supervisor, *strings.Builder) {
	t.Helper()
	exe, _ := os.Executable()
	log := &strings.Builder{}
	supervisor := NewSupervisor(Config{Executable: exe, Args: []string{"-test.run=XXX"}, Env: []string{"GO_WANT_HELPER=1", "HELPER_MODE=" + mode},
		StartTimeout: timeout, StopTimeout: stopFor(mode), Log: log})
	return supervisor, log
}

func TestStartIsReadyAndStopsGracefully(t *testing.T) {
	supervisor, _ := fake(t, "ok", 10*time.Second)
	if err := supervisor.Start(context.Background()); err != nil {
		t.Fatal(err)
	}
	if supervisor.Port == 0 || supervisor.PID == 0 {
		t.Fatal("port and pid must be reported")
	}
	if err := supervisor.Stop(); err != nil {
		t.Fatalf("graceful stop expected, got %v", err)
	}
	select {
	case <-supervisor.Done():
	default:
		t.Fatal("child must be reaped after Stop")
	}
	if supervisor.ExitCode() != 0 {
		t.Fatalf("exit code %d", supervisor.ExitCode())
	}
}

func TestStopForcesAChildThatIgnoresTheRequest(t *testing.T) {
	supervisor, _ := fake(t, "ignore_stop", 10*time.Second)
	if err := supervisor.Start(context.Background()); err != nil {
		t.Fatal(err)
	}
	began := time.Now()
	err := supervisor.Stop()
	if !errors.Is(err, ErrForcedStop) {
		t.Fatalf("expected ErrForcedStop, got %v", err)
	}
	if time.Since(began) > 5*time.Second {
		t.Fatal("forced stop took too long")
	}
	select {
	case <-supervisor.Done():
	default:
		t.Fatal("child must be reaped after a forced stop")
	}
	if alive(supervisor.PID) {
		t.Fatal("child still alive after forced stop")
	}
}

func TestStartupFailuresCleanUpAndAreClassified(t *testing.T) {
	cases := map[string]func(error) bool{
		"exit_immediately": func(err error) bool { var e *ChildExitedError; return errors.As(err, &e) && e.Code == 7 },
		"silent":           func(err error) bool { return errors.Is(err, ErrStartTimeout) },
		"wrong_instance":   func(err error) bool { return errors.Is(err, ErrBadHealth) },
		"foreign_app":      func(err error) bool { return errors.Is(err, ErrBadHealth) },
		"bad_status":       func(err error) bool { return errors.Is(err, ErrBadHealth) },
		"redirect":         func(err error) bool { return errors.Is(err, ErrBadHealth) },
	}
	for mode, expect := range cases {
		t.Run(mode, func(t *testing.T) {
			supervisor, _ := fake(t, mode, 1500*time.Millisecond)
			err := supervisor.Start(context.Background())
			if err == nil || !expect(err) {
				t.Fatalf("unexpected result: %v", err)
			}
			select {
			case <-supervisor.Done():
			case <-time.After(6 * time.Second):
				t.Fatal("a failed start must reap the child")
			}
			if supervisor.PID != 0 && alive(supervisor.PID) {
				t.Fatal("child survived a failed start")
			}
		})
	}
}

func TestSecretsNeverReachArgumentsEnvironmentOrLogs(t *testing.T) {
	supervisor, log := fake(t, "leak", 10*time.Second)
	if err := supervisor.Start(context.Background()); err != nil {
		t.Fatal(err)
	}
	command := strings.Join(supervisor.cmd.Args, " ") + " " + strings.Join(supervisor.cmd.Env, " ")
	if strings.Contains(command, supervisor.handoff.Capability) || strings.Contains(command, supervisor.handoff.InstanceID) {
		t.Fatal("secret on the command line or in the environment")
	}
	time.Sleep(200 * time.Millisecond)
	_ = supervisor.Stop()
	if strings.Contains(log.String(), supervisor.handoff.Capability) || strings.Contains(log.String(), supervisor.handoff.InstanceID) {
		t.Fatalf("secret in the log: %s", log.String())
	}
	if !strings.Contains(log.String(), "<redacted>") {
		t.Fatal("the leaking child should have been redacted, not silenced")
	}
}

func TestEachLaunchHasFreshSecrets(t *testing.T) {
	a, _ := fake(t, "ok", time.Second)
	b, _ := fake(t, "ok", time.Second)
	if a.handoff.Capability == b.handoff.Capability || a.handoff.InstanceID == b.handoff.InstanceID || len(a.handoff.Capability) < 32 {
		t.Fatal("capability and instance id must be unique per launch and at least 32 characters")
	}
}

func TestValidateHealth(t *testing.T) {
	good := `{"app":"sap-lens","instance_id":"abc","status":"loading"}`
	if err := ValidateHealth([]byte(good), "abc"); err != nil {
		t.Fatal(err)
	}
	for _, bad := range []string{`{"app":"sap-lens","instance_id":"x","status":"ok"}`, `{"app":"x","instance_id":"abc","status":"ok"}`, `not json`, `{"app":"sap-lens","instance_id":"abc","status":"down"}`, strings.Repeat("a", 9000)} {
		if err := ValidateHealth([]byte(bad), "abc"); err == nil {
			t.Fatalf("must reject %.30q", bad)
		}
	}
}

func TestWaitHealthyStopsWhenTheChildIsGoneOrTheDeadlinePasses(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(503) }))
	defer server.Close()
	port := server.Listener.Addr().(*net.TCPAddr).Port
	gone := make(chan struct{})
	close(gone)
	if err := WaitHealthy(context.Background(), port, "i", gone, 5*time.Millisecond); !errors.Is(err, errChildGone) {
		t.Fatalf("expected errChildGone, got %v", err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 150*time.Millisecond)
	defer cancel()
	if err := WaitHealthy(ctx, port, "i", make(chan struct{}), 10*time.Millisecond); !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("expected a deadline error, got %v", err)
	}
}

func TestPrepareDataDirRefusesForeignDirectories(t *testing.T) {
	foreign := t.TempDir()
	if err := os.WriteFile(foreign+"/settings.json", []byte("{}"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := PrepareDataDir(foreign); err == nil {
		t.Fatal("a non-empty directory without the experiment marker must be refused")
	}
	if err := PrepareDataDir("relative/path"); err == nil {
		t.Fatal("relative paths must be refused")
	}
	fresh := t.TempDir() + "/data"
	if err := PrepareDataDir(fresh); err != nil {
		t.Fatal(err)
	}
	if err := PrepareDataDir(fresh); err != nil {
		t.Fatalf("a directory this host created is accepted again: %v", err)
	}
}

func TestChildEnvironmentIsMinimalAndSecretFree(t *testing.T) {
	t.Setenv("SAP_LENS_CONFIG_DIR", "/production/looking/path")
	t.Setenv("SOME_TOKEN", "value-that-must-not-leak")
	joined := strings.Join(childEnvironment("/tmp/x"), "\n")
	if strings.Contains(joined, "production") || strings.Contains(joined, "SOME_TOKEN") {
		t.Fatal("the parent's environment must not be inherited")
	}
}
