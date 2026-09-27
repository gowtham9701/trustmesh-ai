# Scenario: Security incident response policy

For suspected credential exposure, analysts must preserve logs, rotate the
affected credential through the approved secret-management workflow, and notify
the security on-call team. TrustMesh may recommend these steps, but it must not
rotate credentials, disable accounts, or modify firewall rules automatically.

Evidence required before declaring exposure confirmed:

- Secret-scanning alert with the matching repository and commit.
- Access logs showing use of the credential.
- Owner confirmation of credential scope.

If any evidence is missing, report the incident as unconfirmed and request the
missing artifact.
