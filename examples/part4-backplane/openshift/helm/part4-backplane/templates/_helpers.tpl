{{- define "part4-backplane.labels" -}}
app.kubernetes.io/part-of: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end -}}

{{/* Container hardening for restricted-v2: no runAsUser/runAsGroup/fsGroup
     anywhere in this chart, so OpenShift assigns a UID from the namespace
     range (annotation openshift.io/sa.scc.uid-range). Every image here
     (ubi10/openjdk-25 S2I, the Python Docker-strategy build off
     ubi10/python-314-minimal, redis:8.10.2-alpine) tolerates an arbitrary
     UID with GID 0. */}}
{{- define "part4-backplane.containerSecurity" -}}
securityContext:
  runAsNonRoot: true
  allowPrivilegeEscalation: false
  capabilities:
    drop: ["ALL"]
  seccompProfile:
    type: RuntimeDefault
{{- end -}}

{{/* dict: root (the top-level $), name (ImageStream name) */}}
{{- define "part4-backplane.image" -}}
{{ .root.Values.registry }}/{{ .root.Release.Namespace }}/{{ .name }}:{{ .root.Values.imageTag }}
{{- end -}}
