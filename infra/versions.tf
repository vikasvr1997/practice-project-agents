terraform {
  required_version = ">= 1.6"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 6.0, < 8.0"
    }
  }

  # Start with local state. Once this works, move state to a GCS bucket:
  # backend "gcs" {
  #   bucket = "YOUR_PROJECT_ID-tfstate"
  #   prefix = "vehicle-agent"
  # }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
