#!/usr/bin/env bash
# make-verify-image.sh <cosign.pub> > verify-image.yaml  (Tag 13, Drill 5)
set -euo pipefail
PUB=${1:-cosign.pub}
{ cat <<'EOF'
# Lab-Policy (Tag 13): nur mit dem Lab-Key signierte Gateway-Images zulassen
apiVersion: policies.kyverno.io/v1
kind: ImageValidatingPolicy
metadata:
  name: verify-llm-gateway
spec:
  validationActions: [Deny]
  matchConstraints:
    resourceRules:
      - apiGroups: [""]
        apiVersions: [v1]
        operations: [CREATE, UPDATE]
        resources: [pods]
  matchImageReferences:
    - glob: "localhost:5055/llm-gateway*"
  attestors:
    - name: lab
      cosign:
        key:
          data: |
EOF
sed 's/^/            /' "$PUB"
cat <<'EOF'
        ctlog:
          insecureIgnoreTlog: true      # Lab: Signatur ohne Rekor-Eintrag
          insecureIgnoreSCT: true
  validations:
    - message: "Image ist nicht mit dem Lab-Key signiert."
      expression: >-
        images.containers.map(i, verifyImageSignatures(i, [attestors.lab]))
        .all(n, n > 0)
EOF
}
