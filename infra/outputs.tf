output "image_repo" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"
}

output "runtime_service_account" {
  value = google_service_account.runtime.email
}

output "build_service_account" {
  value = google_service_account.build.email
}

output "workload_identity_provider" {
  description = "Full resource name for the google-github-actions/auth 'workload_identity_provider' input."
  value       = google_iam_workload_identity_pool_provider.github.name
}
