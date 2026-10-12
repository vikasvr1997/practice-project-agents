# ---------- APIs ----------
locals {
  services = [
    "run.googleapis.com",
    "cloudbuild.googleapis.com",
    "artifactregistry.googleapis.com",
    "secretmanager.googleapis.com",
    "aiplatform.googleapis.com",
    "bigquery.googleapis.com",
    "iam.googleapis.com",
  ]
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

# ---------- CI/CD trigger: every push to main deploys ----------
resource "google_cloudbuild_trigger" "deploy_on_main" {
  count           = var.create_trigger ? 1 : 0
  name            = "${var.service_name}-deploy-main"
  location        = "global"
  filename        = "cloudbuild.yaml"
  service_account = google_service_account.build.id

  github {
    owner = var.github_owner
    name  = var.github_repo
    push {
      branch = "^main$"
    }
  }

  substitutions = {
    _REGION     = var.region
    _REPO       = google_artifact_registry_repository.images.repository_id
    _SERVICE    = var.service_name
    _RUNTIME_SA = google_service_account.runtime.email
    _MODEL      = var.model
  }
}
