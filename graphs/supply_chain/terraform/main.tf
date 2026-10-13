# Sample supply-chain graph (made-up data). NOT part of infra/: you run this
# yourself when you want the supply_chain_analyst agent to have data.
#
#   cd graphs/supply_chain/terraform
#   terraform init
#   terraform plan  -var project_id=YOUR_PROJECT
#   terraform apply -var project_id=YOUR_PROJECT
#
# Then set SUPPLY_CHAIN_GRAPH=YOUR_PROJECT.vehicle_supply_chain.SupplyChain
# (in .env locally, and as a GitHub Actions variable for Cloud Run).
# Change a CSV or graph.sql.tftpl and `terraform apply` reloads only what changed.

terraform {
  required_version = ">= 1.6"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 6.0, < 8.0"
    }
  }
}

provider "google" {
  project = var.project_id
}

variable "project_id" {
  description = "GCP project to create the dataset and graph in."
  type        = string
}

variable "supply_chain_dataset" {
  description = "BigQuery dataset for the supply-chain tables and graph."
  type        = string
  default     = "vehicle_supply_chain"
}

variable "bq_location" {
  description = "Location for the dataset and its bucket, e.g. US or asia-south1."
  type        = string
  default     = "US"
}

resource "google_project_service" "needed" {
  for_each           = toset(["bigquery.googleapis.com", "storage.googleapis.com"])
  service            = each.value
  disable_on_destroy = false
}

locals {
  sc_data_dir = "${path.module}/../data"

  # Table and column descriptions matter: the Graph Creator reads them to find links.
  sc_tables = {
    suppliers = {
      description = "Companies that make parts. Made-up data."
      primary_key = ["supplier_id"]
      schema = [
        { name = "supplier_id", type = "STRING", description = "Unique supplier code" },
        { name = "name", type = "STRING", description = "Supplier company name" },
        { name = "country", type = "STRING", description = "Country of the supplier's main factory" },
        { name = "tier", type = "INT64", description = "1 = ships straight to our plants, 2 = ships to tier-1 suppliers" },
      ]
    }
    plants = {
      description = "Vehicle assembly plants."
      primary_key = ["plant_id"]
      schema = [
        { name = "plant_id", type = "STRING", description = "Unique plant code" },
        { name = "name", type = "STRING", description = "Plant name" },
        { name = "country", type = "STRING", description = "Country" },
      ]
    }
    parts = {
      description = "Parts used to build vehicles."
      primary_key = ["part_id"]
      schema = [
        { name = "part_id", type = "STRING", description = "Unique part number" },
        { name = "name", type = "STRING", description = "Part name" },
        { name = "component", type = "STRING", description = "Component group, matches the recall component" },
        { name = "supplier_id", type = "STRING", description = "References suppliers: the company that makes this part" },
        { name = "unit_cost", type = "FLOAT64", description = "Cost per part in USD" },
      ]
    }
    vehicle_models = {
      description = "Vehicle models and model years."
      primary_key = ["model_id"]
      schema = [
        { name = "model_id", type = "STRING", description = "Unique model code" },
        { name = "name", type = "STRING", description = "Model name" },
        { name = "model_year", type = "INT64", description = "Model year" },
        { name = "body_type", type = "STRING", description = "SUV, sedan, truck or van" },
        { name = "plant_id", type = "STRING", description = "Plant that assembles this model" },
      ]
    }
    part_usage = {
      description = "Which parts each vehicle model uses."
      primary_key = ["part_id", "model_id"]
      schema = [
        { name = "part_id", type = "STRING", description = "The part" },
        { name = "model_id", type = "STRING", description = "The vehicle model that uses it" },
        { name = "qty_per_vehicle", type = "INT64", description = "How many of this part one vehicle needs" },
      ]
    }
    recalls = {
      description = "Safety recall campaigns."
      primary_key = ["recall_id"]
      schema = [
        { name = "recall_id", type = "STRING", description = "Recall campaign number" },
        { name = "report_date", type = "DATE", description = "Date the recall was filed" },
        { name = "component", type = "STRING", description = "Component group with the defect" },
        { name = "severity", type = "STRING", description = "LOW, MEDIUM or HIGH" },
        { name = "summary", type = "STRING", description = "What is wrong" },
      ]
    }
    recall_parts = {
      description = "Parts named in each recall."
      primary_key = ["recall_id", "part_id"]
      schema = [
        { name = "recall_id", type = "STRING", description = "The recall" },
        { name = "part_id", type = "STRING", description = "A recalled part" },
      ]
    }
    recall_models = {
      description = "Vehicle models covered by each recall."
      primary_key = ["recall_id", "model_id"]
      schema = [
        { name = "recall_id", type = "STRING", description = "The recall" },
        { name = "model_id", type = "STRING", description = "An affected vehicle model" },
      ]
    }
    shipments = {
      description = "Part shipments from suppliers to plants."
      primary_key = ["shipment_id"]
      schema = [
        { name = "shipment_id", type = "STRING", description = "Unique shipment number" },
        { name = "supplier_code", type = "STRING", description = "Who shipped it" },
        { name = "plant_id", type = "STRING", description = "Plant that received it" },
        { name = "ship_date", type = "DATE", description = "Date shipped" },
        { name = "units", type = "INT64", description = "Number of parts in the shipment" },
      ]
    }
  }
}

resource "google_bigquery_dataset" "supply_chain" {
  dataset_id  = var.supply_chain_dataset
  location    = var.bq_location
  description = "Made-up vehicle supply-chain data for practising property graphs."

  depends_on = [google_project_service.needed]
}

resource "google_bigquery_table" "supply_chain" {
  for_each            = local.sc_tables
  dataset_id          = google_bigquery_dataset.supply_chain.dataset_id
  table_id            = each.key
  description         = each.value.description
  deletion_protection = false

  schema = jsonencode([
    for c in each.value.schema : { name = c.name, type = c.type, mode = "NULLABLE", description = c.description }
  ])

  # Not enforced by BigQuery, but the Graph Creator and the query planner use it.
  table_constraints {
    primary_key {
      columns = each.value.primary_key
    }
  }
}

# ---------- Load the CSVs ----------
resource "google_storage_bucket" "supply_chain" {
  name                        = "${var.project_id}-supply-chain-data"
  location                    = var.bq_location
  uniform_bucket_level_access = true
  force_destroy               = true

  depends_on = [google_project_service.needed]
}

resource "google_storage_bucket_object" "supply_chain" {
  for_each = local.sc_tables
  bucket   = google_storage_bucket.supply_chain.name
  name     = "${each.key}.csv"
  source   = "${local.sc_data_dir}/${each.key}.csv"
}

resource "google_bigquery_job" "load_supply_chain" {
  for_each = local.sc_tables
  # A new job id when the CSV changes, so Terraform reloads that table.
  job_id   = "load_${each.key}_${substr(filemd5("${local.sc_data_dir}/${each.key}.csv"), 0, 12)}"
  location = var.bq_location

  load {
    source_uris = ["gs://${google_storage_bucket.supply_chain.name}/${google_storage_bucket_object.supply_chain[each.key].name}"]
    destination_table {
      project_id = var.project_id
      dataset_id = google_bigquery_dataset.supply_chain.dataset_id
      table_id   = google_bigquery_table.supply_chain[each.key].table_id
    }
    source_format      = "CSV"
    skip_leading_rows  = 1
    write_disposition  = "WRITE_TRUNCATE"
    create_disposition = "CREATE_NEVER"
  }
}

# ---------- The property graph ----------
locals {
  sc_graph_ddl = templatefile("${path.module}/../graph.sql.tftpl", {
    project = var.project_id
    dataset = var.supply_chain_dataset
  })
}

resource "google_bigquery_job" "supply_chain_graph" {
  # A new job id when the graph changes, so Terraform re-creates it.
  job_id   = "graph_supply_chain_${substr(sha256(local.sc_graph_ddl), 0, 16)}"
  location = var.bq_location

  query {
    query              = local.sc_graph_ddl
    use_legacy_sql     = false
    create_disposition = "" # must be empty for DDL
    write_disposition  = ""
  }

  depends_on = [google_bigquery_table.supply_chain]
}

output "supply_chain_graph" {
  description = "Set SUPPLY_CHAIN_GRAPH to this value."
  value       = "${var.project_id}.${var.supply_chain_dataset}.SupplyChain"
}
