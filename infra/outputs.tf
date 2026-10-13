output "image_repo" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"
}

output "firestore_database" {
  value = google_firestore_database.sessions.name
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

output "proxy_network" {
  value = google_compute_network.proxy_vpc.name
}

output "proxy_subnet" {
  value = google_compute_subnetwork.proxy_subnet.name
}

output "squid_external_ip" {
  description = "Point your local machine's HTTP_PROXY/HTTPS_PROXY at this (with the squid-proxy-password secret value)."
  value       = google_compute_address.squid_external_ip.address
}

output "squid_internal_ip" {
  description = "What Cloud Run's HTTP_PROXY/HTTPS_PROXY point at, reached over Direct VPC Egress."
  value       = google_compute_instance.squid.network_interface[0].network_ip
}
