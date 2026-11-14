//go:build !linux && !windows

package main

import "os/exec"

func configureChild(*exec.Cmd)     {}
func attachToJob(*exec.Cmd) func() { return nil }
func killTree(cmd *exec.Cmd) error {
	if cmd != nil && cmd.Process != nil {
		return cmd.Process.Kill()
	}
	return nil
}
