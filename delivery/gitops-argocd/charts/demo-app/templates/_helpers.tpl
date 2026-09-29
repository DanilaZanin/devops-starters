{{- define "demo-app.fullname" -}}
{{ .Release.Name }}-demo-app
{{- end -}}

{{/*
Selector labels are immutable on a Deployment: keep them to name + instance
only. Anything that changes between releases (chart version, managed-by)
belongs in demo-app.labels, never here.
*/}}
{{- define "demo-app.selectorLabels" -}}
app.kubernetes.io/name: demo-app
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "demo-app.labels" -}}
{{ include "demo-app.selectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{- end -}}
