terraform {
  required_version = ">= 1.0.0"
  required_providers {
    oci = {
      source  = "oracle/oci"
    }
  }
}
provider "oci" {
  tenancy_ocid     = var.tenancy_ocid
  user_ocid        = var.user_ocid
  fingerprint      = var.fingerprint
  private_key_path = var.private_key_path
  region           = var.region
}

data "oci_identity_availability_domains" "ads" {
  compartment_id = var.compartment_id
}

data "oci_core_images" "ubuntu" {
  compartment_id           = var.compartment_id
  operating_system         = "Canonical Ubuntu"
  shape                    = var.shape
  sort_by                  = "TIMECREATED"
  sort_order               = "DESC"

  filter {
    name   = "display_name"
    values = [var.image_name_regex]
    regex  = true
  }
}

data "oci_core_images" "ubuntu_fallback" {
  compartment_id   = var.compartment_id
  operating_system = "Canonical Ubuntu"
  shape            = var.shape
  sort_by          = "TIMECREATED"
  sort_order       = "DESC"
}

locals {
  # Check if the shape name includes "flex" (case-insensitive)
  is_flex = can(regex("flex", lower(var.shape)))
  resolved_image_id = var.image_id != "" ? var.image_id : (
    length(data.oci_core_images.ubuntu.images) > 0 ? data.oci_core_images.ubuntu.images[0].id :
    length(data.oci_core_images.ubuntu_fallback.images) > 0 ? data.oci_core_images.ubuntu_fallback.images[0].id : ""
  )
}

resource "oci_core_instance" "instance" {
  compartment_id      = var.compartment_id
  availability_domain = data.oci_identity_availability_domains.ads.availability_domains[0].name
  shape               = var.shape
  display_name        = "nf-runner-${var.name}"

  dynamic "shape_config" {
    for_each = local.is_flex ? [1] : []
    content {
      ocpus         = var.ocpus
      memory_in_gbs = var.memory_gbs
    }
  }

  source_details {
    source_type               = "image"
    source_id                 = local.resolved_image_id
    boot_volume_size_in_gbs   = var.image_boot_size
  }

  create_vnic_details {
    subnet_id              = var.subnet_id
    assign_public_ip       = false
    skip_source_dest_check = true
  }

  metadata = {
    ssh_authorized_keys = trimspace(var.ssh_authorized_key)

    # Plain bash user-data script that writes and runs the user-defined bootstrap.
    user_data = base64encode(<<-EOT
      #!/bin/bash
      set -euo pipefail
      cat >/bootstrap.sh << EOS
wait_for_apt() {
  while fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1 || \
        fuser /var/lib/dpkg/lock >/dev/null 2>&1 || \
        fuser /var/lib/apt/lists/lock >/dev/null 2>&1 || \
        fuser /var/cache/apt/archives/lock >/dev/null 2>&1; do
    echo "Waiting for other apt/dpkg processes to finish..."
    sleep 5
  done
}

wait_for_apt
apt-get update
apt-get install awscli -y
${var.env_vars}
${var.cmd_script}
EOS
      chmod +x /bootstrap.sh
      echo "Running bootstrap script..."
      /bootstrap.sh
      echo "Bootstrap completed."
    EOT
    )
  }

  lifecycle {
    precondition {
      condition     = local.resolved_image_id != ""
      error_message = "No matching image found. Adjust image_name_regex or set image_id explicitly."
    }
  }
}

output "instance_id" {
  value = oci_core_instance.instance.id
}

output "private_ip" {
  value = oci_core_instance.instance.private_ip
}
