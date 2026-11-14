//go:build windows

package main

import (
	"os/exec"
	"syscall"
	"unsafe"
)

// Windows support is CROSS-COMPILED ONLY in Phase 0 (no Windows machine was available): none of this has been executed.
// A Job Object with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE ends the whole process tree when the host exits or crashes. Only the standard library is used.

var (
	kernel32                     = syscall.NewLazyDLL("kernel32.dll")
	procCreateJobObject          = kernel32.NewProc("CreateJobObjectW")
	procSetInformationJob        = kernel32.NewProc("SetInformationJobObject")
	procAssignProcessToJob       = kernel32.NewProc("AssignProcessToJobObject")
	procTerminateJobObject       = kernel32.NewProc("TerminateJobObject")
	jobObjectExtendedLimit       = uintptr(9)
	jobObjectLimitKillOnJobClose = uint32(0x2000)
)

type ioCounters struct{ a, b, c, d, e, f uint64 }
type basicLimit struct {
	perProcess, perJob int64
	limitFlags         uint32
	minWS, maxWS       uintptr
	active             uint32
	affinity           uintptr
	priority, sched    uint32
}
type extendedLimit struct {
	basic                      basicLimit
	io                         ioCounters
	process, job, peakP, peakJ uintptr
}

func configureChild(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: 0x00000200} // CREATE_NEW_PROCESS_GROUP
}

var jobHandle syscall.Handle

func attachToJob(cmd *exec.Cmd) func() {
	handle, _, _ := procCreateJobObject.Call(0, 0)
	if handle == 0 {
		return nil
	}
	info := extendedLimit{}
	info.basic.limitFlags = jobObjectLimitKillOnJobClose
	if r, _, _ := procSetInformationJob.Call(handle, jobObjectExtendedLimit, uintptr(unsafe.Pointer(&info)), unsafe.Sizeof(info)); r == 0 {
		_ = syscall.CloseHandle(syscall.Handle(handle))
		return nil
	}
	process, err := syscall.OpenProcess(0x1F0FFF, false, uint32(cmd.Process.Pid))
	if err != nil {
		_ = syscall.CloseHandle(syscall.Handle(handle))
		return nil
	}
	defer syscall.CloseHandle(process)
	if r, _, _ := procAssignProcessToJob.Call(handle, uintptr(process)); r == 0 {
		_ = syscall.CloseHandle(syscall.Handle(handle))
		return nil
	}
	jobHandle = syscall.Handle(handle)
	return func() { _ = syscall.CloseHandle(syscall.Handle(handle)) }
}

func killTree(cmd *exec.Cmd) error {
	if jobHandle != 0 {
		if r, _, err := procTerminateJobObject.Call(uintptr(jobHandle), 1); r != 0 {
			return nil
		} else if err != nil {
			_ = err
		}
	}
	if cmd != nil && cmd.Process != nil {
		return cmd.Process.Kill()
	}
	return nil
}
