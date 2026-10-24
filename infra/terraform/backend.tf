# Partial configuration: bucket and prefix are supplied at init time, see backend.hcl.example.
# terraform init -backend-config=backend.hcl
terraform {
  backend "gcs" {}
}
