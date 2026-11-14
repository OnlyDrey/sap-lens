package main

import "strings"

// Redactor removes the launch secrets from any text before it is logged or shown. It is defence in depth: the secrets are never meant to be
// printed by the child, and are never placed on a command line or in an environment.
type Redactor struct{ secrets []string }

func NewRedactor(secrets ...string) *Redactor {
	kept := make([]string, 0, len(secrets))
	for _, secret := range secrets {
		if len(secret) >= 8 {
			kept = append(kept, secret)
		}
	}
	return &Redactor{secrets: kept}
}

func (r *Redactor) Redact(text string) string {
	for _, secret := range r.secrets {
		text = strings.ReplaceAll(text, secret, "<redacted>")
	}
	return text
}
