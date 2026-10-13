# Replicates an enterprise network: a forward proxy (Squid) that most
# egress traffic must go through, with BigQuery (and the metadata server)
# allow-listed to bypass it. Both the local dev machine and Cloud Run point
# HTTP_PROXY/HTTPS_PROXY at this VM; NO_PROXY carves out the exceptions.

# ---------- Network ----------
resource "google_compute_network" "proxy_vpc" {
  name                    = "${var.service_name}-proxy-vpc"
  auto_create_subnetworks = false

  depends_on = [google_project_service.apis]
}

resource "google_compute_subnetwork" "proxy_subnet" {
  name                     = "${var.service_name}-proxy-subnet"
  network                  = google_compute_network.proxy_vpc.id
  region                   = var.region
  ip_cidr_range            = "10.10.0.0/24"
  private_ip_google_access = true # lets anything in this subnet reach Google APIs directly
}

# ---------- Firewall ----------
# Cloud Run reaches Squid over its internal IP via Direct VPC Egress.
resource "google_compute_firewall" "allow_squid_from_subnet" {
  name    = "${var.service_name}-allow-squid-from-subnet"
  network = google_compute_network.proxy_vpc.name

  allow {
    protocol = "tcp"
    ports    = ["3128"]
  }
  source_ranges = [google_compute_subnetwork.proxy_subnet.ip_cidr_range]
  target_tags   = ["squid-proxy"]
}

# Your local machine reaches Squid over its external IP. Open because Squid
# requires authenticated CONNECT (see squid_password below) — same trust
# model as a real corporate proxy reachable from the internet.
resource "google_compute_firewall" "allow_squid_from_internet" {
  name    = "${var.service_name}-allow-squid-from-internet"
  network = google_compute_network.proxy_vpc.name

  allow {
    protocol = "tcp"
    ports    = ["3128"]
  }
  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["squid-proxy"]
}

# SSH to the VM for debugging, via IAP's tunnel (no public SSH port exposed).
resource "google_compute_firewall" "allow_iap_ssh" {
  name    = "${var.service_name}-allow-iap-ssh"
  network = google_compute_network.proxy_vpc.name

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
  source_ranges = ["35.235.240.0/20"]
  target_tags   = ["squid-proxy"]
}

# ---------- Squid's proxy-auth password ----------
# Empty secret, same as app_api_key: the value never lands in Git or
# Terraform state. Add it yourself after apply:
#   openssl rand -hex 24 | gcloud secrets versions add squid-proxy-password --data-file=-
resource "google_secret_manager_secret" "squid_proxy_password" {
  secret_id = "squid-proxy-password"
  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

# ---------- Squid VM's own identity ----------
resource "google_service_account" "squid_vm" {
  account_id   = "${var.service_name}-squid-vm"
  display_name = "Squid proxy VM"
}

resource "google_secret_manager_secret_iam_member" "squid_vm_reads_password" {
  secret_id = google_secret_manager_secret.squid_proxy_password.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.squid_vm.email}"
}

# ---------- The VM ----------
resource "google_compute_address" "squid_external_ip" {
  name   = "${var.service_name}-squid-ip"
  region = var.region
}

resource "google_compute_instance" "squid" {
  name         = "${var.service_name}-squid"
  machine_type = "e2-micro"
  zone         = "${var.region}-a"
  tags         = ["squid-proxy"]

  boot_disk {
    initialize_params {
      image = "debian-cloud/debian-12"
    }
  }

  network_interface {
    subnetwork = google_compute_subnetwork.proxy_subnet.id
    access_config {
      nat_ip = google_compute_address.squid_external_ip.address
    }
  }

  service_account {
    email  = google_service_account.squid_vm.email
    scopes = ["cloud-platform"]
  }

  metadata_startup_script = templatefile("${path.module}/squid-startup.sh.tftpl", {
    project_id = var.project_id
  })
}
