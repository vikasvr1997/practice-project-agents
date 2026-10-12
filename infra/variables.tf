variable "project_id" {
  description = "Your GCP project ID."
  type        = string
}

variable "region" {
  description = "Region for Cloud Run and Artifact Registry."
  type        = string
  default     = "us-central1"
}

variable "service_name" {
  description = "Name used for the Cloud Run service and the image repository."
  type        = string
  default     = "vehicle-agent"
}

variable "github_owner" {
  description = "Your GitHub username."
  type        = string
}

variable "github_repo" {
  description = "Your GitHub repository name."
  type        = string
}

