{{- define "demo-app.fullname" -}}
{{ .Release.Name }}-demo-app
{{- end -}}

{{- define "demo-app.labels" -}}
app.kubernetes.io/name: demo-app
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}
