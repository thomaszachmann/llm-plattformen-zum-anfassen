{{- define "llm-platform.fullname" -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "llm-platform.labels" -}}
app.kubernetes.io/part-of: llm-platform
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}

{{/* Image mit optionaler Air-Gap-Registry: (dict "img" .. "global" ..) */}}
{{- define "llm-platform.image" -}}
{{- $reg := .global.imageRegistry | default "" -}}
{{- if $reg -}}
{{- printf "%s/%s:%s" (trimSuffix "/" $reg) .img.repository (toString .img.tag) -}}
{{- else -}}
{{- printf "%s:%s" .img.repository (toString .img.tag) -}}
{{- end -}}
{{- end -}}

{{- define "llm-platform.pullSecrets" -}}
{{- with .Values.global.imagePullSecrets }}
imagePullSecrets:
{{- range . }}
  - name: {{ . }}
{{- end }}
{{- end }}
{{- end -}}

{{- define "llm-platform.secretName" -}}
{{- .Values.gateway.existingSecret | default (printf "%s-tenants" (include "llm-platform.fullname" .)) -}}
{{- end -}}
