# Windows code signing readiness

## Status and publisher model

SAP Lens produces an **unsigned** executable. Signing is not configured or activated
by this work. Historical Windows Actions builds verified unsigned packages; that
evidence does not validate later packaging changes. See
[packaging readiness](WINDOWS_PACKAGING.md) for the exact validation boundary.
Signing, a successful browser download and SmartScreen reputation are different
properties. A signature neither guarantees successful downloads nor guarantees the
absence of SmartScreen or endpoint-security warnings.

The intended future publisher is an individual using their **validated legal
personal name**, not an invented company identity. The existing PE `CompanyName`
(`SAP Lens contributors`) is descriptive product metadata, not an Authenticode
publisher identity. Preserve approved product metadata; agree any future metadata
change separately. Do not represent an informal contributor label as a legally
validated publisher.

## Eligibility research — 21 October 2026

Microsoft calls the service **Artifact Signing** (formerly Trusted Signing).
Microsoft's [official quickstart](https://learn.microsoft.com/azure/artifact-signing/quickstart)
states: “Individual developers must be located in the United States or Canada.”
Its separate list of supported **organizations** includes Norway. Consequently,
this source does **not** establish eligibility for a Norwegian individual; Norway
must not be inferred from the organization list or Azure region availability.
Private Trust is a different trust model and does not solve public distribution
trust on arbitrary customer PCs.

The quickstart and FAQ were retrieved from Microsoft's official documentation
repository on the verification date:

- [Quickstart source](https://github.com/MicrosoftDocs/azure-docs/blob/main/articles/artifact-signing/quickstart.md)
- [Microsoft FAQ](https://learn.microsoft.com/azure/artifact-signing/faq)
- [FAQ source](https://github.com/MicrosoftDocs/azure-docs/blob/main/articles/artifact-signing/faq.yml)
- [Service overview](https://learn.microsoft.com/azure/artifact-signing/overview)

Eligibility changes over time. Recheck the primary source and obtain a provider's
written confirmation for the applicant's actual country and individual status
before enrollment. An Azure subscription or an EU/EEA address alone is not proof.
No account, identity-validation request or signing resource was created.

## Alternatives and costs

An Individual Validation (IV) code-signing certificate identifies a natural person.
It requires verification of legal name, government-issued identity and often
address/contact details. Requirements, supported countries, certificate names and
remote-signing availability are provider-specific. Organization/EV offers must not
be assumed suitable for an unregistered individual.

| Candidate to investigate | Eligibility and protection questions | Cost evidence on verification date |
|---|---|---|
| [Certum](https://shop.certum.eu/open-source-code-signing-certificate.html) | Confirm Norwegian IV availability, open-source conditions, supported token/cloud product and identity checks | Current price could not be retrieved from this environment; certificate, token/cloud subscription, shipping and VAT need a dated quote |
| [GlobalSign](https://www.globalsign.com/en/code-signing-certificate) | Confirm whether an individual, rather than only an organization, can enroll from Norway; confirm approved hardware/cloud key storage | No verified current Norwegian individual quote; do not substitute an organization price |
| [Sectigo](https://www.sectigo.com/ssl-certificates-tls/code-signing) or an authorized reseller | Confirm the specific IV product and issuing CA accepts Norwegian individuals; distinguish reseller marketing from CA eligibility | No verified current quote; include certificate term and hardware/cloud signing charges |
| [Microsoft Artifact Signing pricing](https://azure.microsoft.com/pricing/details/artifact-signing/) | Public-trust individual eligibility currently excludes Norway in the retrieved quickstart | Pricing page could not be retrieved; even a low subscription price would not establish eligibility |

Vendor/pricing pages could not be retrieved through this environment's restricted
network. **No defensible current cost estimate in NOK is available**, and no price
or Norwegian individual support is asserted for those CA candidates. The links are
future due-diligence sources, not verified purchase recommendations. Avoid stale
promotional prices. Obtain comparable dated quotes covering certificate validity,
renewal, token/HSM purchase or cloud subscription, per-signature allowance,
timestamping, shipping, exchange rate and Norwegian VAT before setting a budget.
This limitation is preferable to inventing a current amount or eligible provider.

Keys must use the CA's approved hardware-backed protection, such as an appropriate
FIPS/CC-certified token or managed HSM. Do not export a private signing key into a
repository, generic runner file or GitHub artifact. A USB token attached to a PC is
not automatically usable from a hosted Actions runner; either a controlled signing
machine or an approved cloud/HSM integration is needed. Investigate provider key
attestation, authorization scope, audit trail, revocation and recovery requirements.

For cloud signing, prefer short-lived federated identity/OIDC and narrowly scoped
signing authorization where the selected provider supports it. Do not assume an
IV certificate is compatible with a particular cloud service. No credentials,
placeholder secrets or provider actions are added in this milestone.

## Future protected release pipeline

Unsigned development builds remain the default manual workflow. A future signed
release needs a separately reviewed protected environment and release policy:

1. Build from an approved immutable source commit using the canonical build.
2. Verify the unsigned PE, resources, frontend, archive privacy and tests.
3. Require protected release approval before granting signing authorization.
4. Sign with the approved service using the expected personal publisher identity.
5. Apply a trusted RFC 3161 timestamp with SHA-256, using the provider's supported TSA.
6. Verify Authenticode on Windows, including the signature chain and trusted timestamp.
7. Validate the exact expected publisher and certificate policy; “a valid signature”
   from an unexpected publisher is insufficient.
8. **Generate the final executable SHA-256 after signing and timestamping**, because
   those operations change executable bytes. Reverify package resources/archive.
9. Upload the signed executable and matching final manifest; verify the downloaded
   artifact against that exact final digest.
10. Perform Windows distribution acceptance from the downloaded ZIP, including
    Explorer launch, WebView2, CSV picker/network-share access and settings upgrades.

A trusted timestamp can preserve validation of a signature made while a certificate
was valid after normal certificate expiry; it is not a guarantee against revocation
or later trust-policy changes. Renew certificates/identity validation before expiry,
monitor signing failures and plan publisher continuity during renewal. Microsoft's
FAQ notes that expired identity validation stops profile renewal and signing.
Never assume a renewed certificate has the same thumbprint. Validate the permitted
publisher/certificate policy explicitly during rollover and retain signing records.

## Future human prerequisites — no action requested now

- Select an eligible IV provider after confirming Norway support and current costs.
- Complete personal identity verification and choose the displayed legal publisher.
- Purchase/provision the approved hardware-backed or cloud signing capability.
- Approve credential/federation scope, access review and incident/revocation procedures.
- Approve protected release environments and required release reviewers.
- Validate certificate renewal, timestamping and target-PC distribution behavior.

These are documentation items only. No purchase, enrollment, credentials, signing
attempt or automatic release publication is part of this task.
