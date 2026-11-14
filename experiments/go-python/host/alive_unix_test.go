//go:build !windows

package main

import (
	"os"
	"syscall"
)

// alive reports whether a process with this id still exists (signal 0 probes without delivering anything).
func alive(pid int) bool {
	process, err := os.FindProcess(pid)
	return err == nil && process.Signal(syscall.Signal(0)) == nil
}
