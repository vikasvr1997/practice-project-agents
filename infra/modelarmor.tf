# ---------- Model Armor: guardrails for prompts and answers ----------
# One template screens both directions. After `terraform apply`, copy the
# `model_armor_template` output into the MODEL_ARMOR_TEMPLATE GitHub Actions
# variable (and your .env for local runs). Empty = guardrails off.

resource "google_project_service" "modelarmor" {
  service            = "modelarmor.googleapis.com"
  disable_on_destroy = false
}

resource "google_model_armor_template" "guard" {
  location    = var.region
  template_id = "${var.service_name}-guard"

  filter_config {
    # Responsible AI filters: block clearly harmful content.
    rai_settings {
      rai_filters {
        filter_type      = "HATE_SPEECH"
        confidence_level = "MEDIUM_AND_ABOVE"
      }
      rai_filters {
        filter_type      = "HARASSMENT"
        confidence_level = "MEDIUM_AND_ABOVE"
      }
      rai_filters {
        filter_type      = "DANGEROUS"
        confidence_level = "MEDIUM_AND_ABOVE"
      }
      rai_filters {
        filter_type      = "SEXUALLY_EXPLICIT"
        confidence_level = "MEDIUM_AND_ABOVE"
      }
    }

    # "Ignore your instructions..." style attacks.
    pi_and_jailbreak_filter_settings {
      filter_enforcement = "ENABLED"
      confidence_level   = "MEDIUM_AND_ABOVE"
    }

    # Phishing or malware links in prompts or answers.
    malicious_uri_filter_settings {
      filter_enforcement = "ENABLED"
    }

    # Sensitive data (card numbers, SSNs and similar) via Sensitive Data Protection.
    sdp_settings {
      basic_config {
        filter_enforcement = "ENABLED"
      }
    }
  }

  template_metadata {
    # Log each screening so you can review what was blocked and tune thresholds.
    log_sanitize_operations = true
  }

  depends_on = [google_project_service.modelarmor]
}

# The app calls Model Armor as its runtime service account.
resource "google_project_iam_member" "runtime_modelarmor" {
  project = var.project_id
  role    = "roles/modelarmor.user"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

output "model_armor_template" {
  value = google_model_armor_template.guard.id
}
