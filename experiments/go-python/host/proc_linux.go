//go:build linux

package main

import (
	"os/exec"
	"syscall"
)

// configureChild puts the child in its own process group and asks the kernel to kill it if this process dies. The backend also exits when
// its stdin closes, so an orphan is prevented even if Pdeathsig is unavailable (it is tied to the creating thread, hence main locks its thread).
func configureChild(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true, Pdeathsig: syscall.SIGKILL}
}

func attachToJob(*exec.Cmd) func() { return nil }

// killTree terminates the whole process group of the child.
func killTree(cmd *exec.Cmd) error {
	if cmd == nil || cmd.Process == nil {
		return nil
	}
	if err := syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL); err != nil && err != syscall.ESRCH {
		return err
	}
	return nil
}
