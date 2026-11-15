package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"path/filepath"
	"runtime"
	"strconv"
	"syscall"
	"time"
)

func init() {
	// Pdeathsig is bound to the thread that created the child; keep that thread alive for the life of the process.
	runtime.LockOSThread()
}

const markerName = ".sap-lens-poc"
const markerText = "sap-lens-poc-v1\n"

// PrepareDataDir creates (or accepts) an ISOLATED experiment directory. It refuses an existing non-empty directory that this host did not mark
// itself, so the experiment can never be pointed at real SAP Lens data by mistake.
func PrepareDataDir(path string) error {
	if !filepath.IsAbs(path) {
		return errors.New("data directory must be absolute")
	}
	marker := filepath.Join(path, markerName)
	entries, err := os.ReadDir(path)
	switch {
	case err == nil && len(entries) > 0:
		content, readErr := os.ReadFile(marker)
		if readErr != nil || string(content) != markerText {
			return errors.New("refusing a non-empty directory that is not an experiment data directory")
		}
		return nil
	case err != nil && !os.IsNotExist(err):
		return err
	}
	if err := os.MkdirAll(path, 0o700); err != nil {
		return err
	}
	return os.WriteFile(marker, []byte(markerText), 0o600)
}

// isolatedDirs are created below the data directory so every location a Python library might fall back to (temporary files, home, application data)
// resolves inside the isolated experiment directory, never to the user's real profile or to a machine-wide folder such as C:\TEMP.
var isolatedDirs = []string{"tmp", "home", "appdata", "localappdata", "programdata"}

// PrepareIsolatedDirs creates the redirect targets of childEnvironment. data must already be a prepared experiment directory.
func PrepareIsolatedDirs(data string) error {
	for _, name := range isolatedDirs {
		if err := os.MkdirAll(filepath.Join(data, name), 0o700); err != nil {
			return err
		}
	}
	return nil
}

// childEnvironment is the complete, minimal environment of the backend. The capability is deliberately NOT part of it.
// Temporary, home and application-data variables all point into the isolated data directory (see PrepareIsolatedDirs).
func childEnvironment(data string) []string {
	dir := func(name string) string { return filepath.Join(data, name) }
	env := []string{"SAP_LENS_POC_DATA=" + data, "PYTHONUTF8=1", "PYTHONDONTWRITEBYTECODE=1", "LANG=C.UTF-8"}
	if runtime.GOOS == "windows" {
		env = append(env, "SYSTEMROOT="+os.Getenv("SYSTEMROOT"), "PATH="+os.Getenv("SYSTEMROOT")+`\System32`,
			"TEMP="+dir("tmp"), "TMP="+dir("tmp"), "USERPROFILE="+dir("home"), "APPDATA="+dir("appdata"), "LOCALAPPDATA="+dir("localappdata"), "PROGRAMDATA="+dir("programdata"))
	} else {
		env = append(env, "PATH=/usr/bin:/bin", "TMPDIR="+dir("tmp"), "HOME="+dir("home"), "XDG_CONFIG_HOME="+dir("appdata"), "XDG_DATA_HOME="+dir("localappdata"))
	}
	return env
}

func pythonPaths(runtimeDir string) (string, error) {
	candidates := []string{filepath.Join(runtimeDir, "python", "bin", "python3"), filepath.Join(runtimeDir, "python", "python.exe")}
	for _, candidate := range candidates {
		if info, err := os.Stat(candidate); err == nil && !info.IsDir() {
			return candidate, nil
		}
	}
	return "", errors.New("no Python interpreter in the runtime tree")
}

func main() { os.Exit(run(os.Args[1:])) }

func run(args []string) int {
	flags := flag.NewFlagSet("saplens-host", flag.ContinueOnError)
	runtimeDir := flags.String("runtime", "", "assembled runtime tree (python/ and app/)")
	data := flags.String("data", "", "isolated experiment data directory (absolute; created empty or previously created by this host)")
	startTimeout := flags.Duration("start-timeout", 30*time.Second, "time allowed until a validated health response")
	stopTimeout := flags.Duration("stop-timeout", 8*time.Second, "time allowed for a graceful stop before the backend is terminated")
	exitAfterReady := flags.Bool("exit-after-ready", false, "stop right after readiness (measurements)")
	hold := flags.Duration("hold", 0, "stop after this long once ready (0 = until a signal)")
	if err := flags.Parse(args); err != nil {
		return ExitUsage
	}
	if *runtimeDir == "" || *data == "" {
		fmt.Fprintln(os.Stderr, "usage: saplens-host --runtime DIR --data DIR [--start-timeout D] [--stop-timeout D] [--exit-after-ready] [--hold D]")
		return ExitUsage
	}
	if err := PrepareDataDir(*data); err != nil {
		fmt.Fprintln(os.Stderr, "data directory:", err)
		return ExitStartFailure
	}
	if err := PrepareIsolatedDirs(*data); err != nil {
		fmt.Fprintln(os.Stderr, "data directory:", err)
		return ExitStartFailure
	}
	python, err := pythonPaths(*runtimeDir)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return ExitStartFailure
	}
	// The backend dumps every thread's stack to stderr this long after it starts if it is still not serving: it shows WHERE a stalled start is stuck.
	dumpAfter := int(startTimeout.Seconds()) - 2
	if dumpAfter < 1 {
		dumpAfter = 1
	}
	environment := append(childEnvironment(*data), "SAP_LENS_POC_DUMP_AFTER="+strconv.Itoa(dumpAfter))
	supervisor := NewSupervisor(Config{
		Executable: python, Args: []string{"-I", "-m", "poc_backend"}, Dir: *data, Env: environment,
		StartTimeout: *startTimeout, StopTimeout: *stopTimeout, Log: os.Stderr,
	})
	signals := make(chan os.Signal, 2)
	signal.Notify(signals, os.Interrupt, syscall.SIGTERM)
	context0, cancel := context.WithCancel(context.Background())
	defer cancel()
	go func() { <-signals; cancel() }()
	started := time.Now()
	if err := supervisor.Start(context0); err != nil {
		fmt.Fprintln(os.Stderr, "start failed:", err)
		fmt.Fprintf(os.Stderr, "host: exit_code_meaning=%s\n", startFailureMeaning(err))
		var exited *ChildExitedError
		switch {
		case errors.Is(err, ErrStartTimeout):
			return ExitStartTimeout
		case errors.As(err, &exited):
			return ExitBackendExited
		}
		return ExitStartFailure
	}
	fmt.Printf("READY url=http://127.0.0.1:%d/ pid=%d ms=%d\n", supervisor.Port, supervisor.PID, time.Since(started).Milliseconds())
	if *exitAfterReady {
		return stopCode(supervisor.Stop())
	}
	var limit <-chan time.Time
	if *hold > 0 {
		limit = time.After(*hold)
	}
	select {
	case <-context0.Done():
	case <-limit:
	case <-supervisor.Done():
		fmt.Fprintln(os.Stderr, "backend exited unexpectedly with code", supervisor.ExitCode())
		_ = supervisor.Stop()
		return ExitBackendExited
	}
	return stopCode(supervisor.Stop())
}

// startFailureMeaning names the exit code in the diagnostic output so a reader of the log does not need this source.
func startFailureMeaning(err error) string {
	var exited *ChildExitedError
	switch {
	case errors.Is(err, ErrStartTimeout):
		return "3 start timeout (the backend was still running but did not become ready)"
	case errors.As(err, &exited):
		return "4 backend exited before it was ready"
	}
	return "2 start failure"
}

func stopCode(err error) int {
	switch {
	case err == nil:
		return ExitOK
	case errors.Is(err, ErrForcedStop):
		fmt.Fprintln(os.Stderr, "stop:", err)
		return ExitOK // the backend is gone; the message records that it had to be terminated
	default:
		fmt.Fprintln(os.Stderr, "stop:", err)
		return ExitStartFailure
	}
}
