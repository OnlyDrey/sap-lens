//go:build windows

package main

import "syscall"

// alive reports whether the process is still running (exit code STILL_ACTIVE). Not executed in Phase 0 (cross-compiled only).
func alive(pid int) bool {
	handle, err := syscall.OpenProcess(syscall.PROCESS_QUERY_INFORMATION, false, uint32(pid))
	if err != nil {
		return false
	}
	defer syscall.CloseHandle(handle)
	var code uint32
	return syscall.GetExitCodeProcess(handle, &code) == nil && code == 259
}
