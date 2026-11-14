package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"strconv"
	"time"
)

var errChildGone = errors.New("backend exited while waiting for readiness")

// healthClient talks to the loopback listener only: no proxy, no redirects, no TLS, short timeouts.
func healthClient() *http.Client {
	return &http.Client{
		Timeout: 750 * time.Millisecond,
		Transport: &http.Transport{
			Proxy:             nil,
			DisableKeepAlives: true,
			DialContext:       (&net.Dialer{Timeout: 500 * time.Millisecond}).DialContext,
		},
		CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
	}
}

// ValidateHealth applies the same rules as the current desktop readiness probe: the response must be the owned SAP Lens instance
// (application name and the per-launch instance id) in a status that means "up", and must be small.
func ValidateHealth(body []byte, instanceID string) error {
	if len(body) > 8192 {
		return fmt.Errorf("%w: oversized", ErrBadHealth)
	}
	var health struct {
		App        string `json:"app"`
		InstanceID string `json:"instance_id"`
		Status     string `json:"status"`
	}
	if err := json.Unmarshal(body, &health); err != nil {
		return fmt.Errorf("%w: not JSON", ErrBadHealth)
	}
	if health.App != "sap-lens" || health.InstanceID != instanceID {
		return fmt.Errorf("%w: another service or instance", ErrBadHealth)
	}
	switch health.Status {
	case "ok", "loading", "needs_configuration":
		return nil
	}
	return fmt.Errorf("%w: status %q", ErrBadHealth, health.Status)
}

// WaitHealthy polls /health on 127.0.0.1 until the owned backend answers. A foreign or malformed answer is a hard failure (never retried into
// "success"); connection errors are retried until the deadline or until the child exits.
func WaitHealthy(ctx context.Context, port int, instanceID string, gone <-chan struct{}, interval time.Duration) error {
	client := healthClient()
	url := "http://" + net.JoinHostPort("127.0.0.1", strconv.Itoa(port)) + "/health"
	for {
		select {
		case <-gone:
			return errChildGone
		case <-ctx.Done():
			return ctx.Err()
		default:
		}
		request, _ := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
		response, err := client.Do(request)
		if err == nil {
			body, readErr := io.ReadAll(io.LimitReader(response.Body, 8193))
			_ = response.Body.Close()
			if response.StatusCode >= 300 && response.StatusCode < 400 {
				return fmt.Errorf("%w: redirect refused", ErrBadHealth)
			}
			if response.StatusCode == http.StatusOK && readErr == nil {
				return ValidateHealth(body, instanceID)
			}
		}
		select {
		case <-gone:
			return errChildGone
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(interval):
		}
	}
}
