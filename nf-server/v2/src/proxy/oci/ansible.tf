# Stage 2, setup the systemd running job

resource "null_resource" "bootstrap_submit" {
  depends_on = [oci_core_instance.instance]

  provisioner "local-exec" {
    command = <<-EOT
      set -e

      TARGET="${oci_core_instance.instance.private_ip}"
      BASTION="${var.bastion_user}@${var.bastion_host}"
      BASTION_KEY="${var.bastion_private_key_path}"
      VM_KEY="${var.vm_private_key_path}"
      VM_USER="${var.ssh_user}"

      INVENTORY=$(mktemp)
      echo "[vm]" > $INVENTORY
      echo "$TARGET ansible_user=$VM_USER ansible_ssh_private_key_file=$VM_KEY" >> $INVENTORY

      echo "[vm:vars]" >> $INVENTORY
      echo "ansible_ssh_common_args='-o ProxyCommand=\"ssh -i $BASTION_KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null $BASTION -W %h:%p\" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null'" >> $INVENTORY

      ansible-playbook -i $INVENTORY ${path.module}/bootstrap_submit.yml

      rm -f $INVENTORY
    EOT
  }
}

# Stage 3, check running job status once

resource "null_resource" "bootstrap_check" {
  depends_on = [null_resource.bootstrap_submit]

  triggers = {
    always_run = timestamp()
  }

  provisioner "local-exec" {
    command = <<-EOT
      set -e

      TARGET="${oci_core_instance.instance.private_ip}"
      BASTION="${var.bastion_user}@${var.bastion_host}"
      BASTION_KEY="${var.bastion_private_key_path}"
      VM_KEY="${var.vm_private_key_path}"
      VM_USER="${var.ssh_user}"

      INVENTORY=$(mktemp)
      echo "[vm]" > $INVENTORY
      echo "$TARGET ansible_user=$VM_USER ansible_ssh_private_key_file=$VM_KEY" >> $INVENTORY

      echo "[vm:vars]" >> $INVENTORY
      echo "ansible_ssh_common_args='-o ProxyCommand=\"ssh -i $BASTION_KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null $BASTION -W %h:%p\" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null'" >> $INVENTORY

      ansible-playbook -i $INVENTORY ${path.module}/bootstrap_check.yml

      rm -f $INVENTORY
    EOT
  }
}

# Stage 4, wait for running job to finish

resource "null_resource" "bootstrap_wait" {
  depends_on = [null_resource.bootstrap_submit]

  triggers = {
    always_run = timestamp()
  }

  provisioner "local-exec" {
    command = <<-EOT
      set -e

      TARGET="${oci_core_instance.instance.private_ip}"
      BASTION="${var.bastion_user}@${var.bastion_host}"
      BASTION_KEY="${var.bastion_private_key_path}"
      VM_KEY="${var.vm_private_key_path}"
      VM_USER="${var.ssh_user}"

      INVENTORY=$(mktemp)
      echo "[vm]" > $INVENTORY
      echo "$TARGET ansible_user=$VM_USER ansible_ssh_private_key_file=$VM_KEY" >> $INVENTORY

      echo "[vm:vars]" >> $INVENTORY
      echo "ansible_ssh_common_args='-o ProxyCommand=\"ssh -i $BASTION_KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null $BASTION -W %h:%p\" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null'" >> $INVENTORY

      ansible-playbook -i $INVENTORY ${path.module}/bootstrap_wait.yml

      rm -f $INVENTORY
    EOT
  }
}
