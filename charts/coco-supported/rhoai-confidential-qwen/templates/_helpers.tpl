{{/* Copy configuration into private guest tmpfs, verify the measured inventory,
     then execute it. Host ConfigMap updates cannot modify the verified copy. */}}
{{- define "qwen.command" -}}
{{- $root := .root -}}
{{- $role := .role -}}
{{- $lines := list "set -euo pipefail" (printf "export DEMO_CONFIG=/dev/shm/verified-%s" $role) "mkdir -p -m 0700 \"$DEMO_CONFIG\"" -}}
{{- $hashes := list -}}
{{- range $path, $_ := $root.Files.Glob "files/*.sh" -}}
{{- $name := base $path -}}
{{- $lines = append $lines (printf "cp -L /opt/demo/%s \"$DEMO_CONFIG/%s\"" $name $name) -}}
{{- $hashes = append $hashes (printf "%s  %s" (sha256sum ($root.Files.Get $path)) $name) -}}
{{- end -}}
{{- $lines = append $lines "cp -L /opt/demo/model.sha256 \"$DEMO_CONFIG/model.sha256\"" -}}
{{- $hashes = append $hashes (printf "%s  model.sha256" (sha256sum ($root.Files.Get "files/model.sha256"))) -}}
{{- if and (eq $role "storage-initializer") (eq $root.Values.distribution.backend "s3") $root.Values.distribution.s3.caBundle -}}
{{- $lines = append $lines "cp -L /opt/s3-ca/ca.crt \"$DEMO_CONFIG/s3-ca.crt\"" -}}
{{- $hashes = append $hashes (printf "%s  s3-ca.crt" (sha256sum $root.Values.distribution.s3.caBundle)) -}}
{{- end -}}
{{- if eq $role "chat" -}}
{{- range $name := list "server.py" "index.html" -}}
{{- $lines = append $lines (printf "cp -L /app/%s \"$DEMO_CONFIG/%s\"" $name $name) -}}
{{- $hashes = append $hashes (printf "%s  %s" (sha256sum ($root.Files.Get (printf "files/%s" $name))) $name) -}}
{{- end -}}
{{- $lines = append $lines "export CHAT_FILES=$DEMO_CONFIG" -}}
{{- end -}}
{{- $lines = append $lines (printf "cd \"$DEMO_CONFIG\"\nsha256sum -c <<'INVENTORY'\n%s\nINVENTORY" (join "\n" $hashes)) -}}
{{- $lines = append $lines (printf "exec /bin/bash \"$DEMO_CONFIG/%s\"" .entry) -}}
{{- list "/bin/bash" "-ec" (join "\n" $lines) | toJson -}}
{{- end -}}
