# ---------- APIs ----------
locals {
  services = [
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "secretmanager.googleapis.com",
    "aiplatform.googleapis.com",
    "bigquery.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "compute.googleapis.com",
    "firestore.googleapis.com",
  ]
}

data "google_project" "this" {
  project_id = var.project_id
}

resource "google_project_service" "apis" {
  for_each           = toset(local.services)
  service            = each.value
  disable_on_destroy = false
}

# ---------- Artifact Registry (Docker images) ----------
resource "google_artifact_registry_repository" "images" {
  location      = var.region
  repository_id = var.service_name
  format        = "DOCKER"

  cleanup_policies {
    id     = "keep-last-10"
    action = "KEEP"
    most_recent_versions {
      keep_count = 10
    }
  }

  depends_on = [google_project_service.apis]
}

# ---------- Secret: the API key that protects /ask ----------
# Terraform creates the empty secret; you add the value with gcloud
# so the key never ends up in Terraform state or Git.
resource "google_secret_manager_secret" "app_api_key" {
  secret_id = "app-api-key"
  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

# ---------- Firestore (session persistence) ----------
resource "google_firestore_database" "sessions" {
  name        = "(default)"
  location_id = var.firestore_location
  type        = "FIRESTORE_NATIVE"

  depends_on = [google_project_service.apis]
}

# ---------- Runtime service account (what the app runs as) ----------
resource "google_service_account" "runtime" {
  account_id   = "${var.service_name}-run"
  display_name = "Vehicle agent Cloud Run runtime"
}

resource "google_project_iam_member" "runtime_roles" {
  for_each = toset([
    "roles/bigquery.jobUser", # run BigQuery queries
    "roles/bigquery.dataViewer",
    "roles/aiplatform.user", # call Gemini through Vertex AI
    "roles/logging.logWriter",
    "roles/datastore.user", # read/write Firestore sessions
  ])
  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_secret_manager_secret_iam_member" "runtime_reads_key" {
  secret_id = google_secret_manager_secret.app_api_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}

# ---------- Build service account (what Cloud Build runs as) ----------
resource "google_service_account" "build" {
  account_id   = "${var.service_name}-build"
  display_name = "Vehicle agent Cloud Build"
}

resource "google_project_iam_member" "build_roles" {
  for_each = toset([
    "roles/run.admin",
    "roles/artifactregistry.writer",
    "roles/logging.logWriter",
    "roles/compute.networkUser", # lets the deploy attach Cloud Run to the proxy VPC
  ])
  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.build.email}"
}

# Lets Cloud Build deploy a service that runs as the runtime account.
resource "google_service_account_iam_member" "build_acts_as_runtime" {
  service_account_id = google_service_account.runtime.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.build.email}"
}

# ---------- CI/CD: let GitHub Actions impersonate the build SA via OIDC ----------
# No long-lived key leaves GCP; GitHub's OIDC token proves which repo is asking.
resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "${var.service_name}-github"
  display_name              = "GitHub Actions"

  depends_on = [google_project_service.apis]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id         = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github"
  display_name                      = "GitHub"

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
  }
  # Only workflows running in this exact repo can mint tokens for it.
  attribute_condition = "assertion.repository == \"${var.github_owner}/${var.github_repo}\""

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account_iam_member" "github_actions_impersonates_build" {
  service_account_id = google_service_account.build.name
  role                = "roles/iam.workloadIdentityUser"
  member              = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_owner}/${var.github_repo}"
}
