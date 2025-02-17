# terraform-rum-analysis
This repository contains tools that can be used to analyse Terraform's resources under management in a single workspace.
There are 3 main scripts:

`terraform_resource_extractor.py`:

Purpose: Analyzes a Terraform state (.tfstate) file to extract and aggregate managed resources.
Features:
Extracts managed resources from the state file.
Counts total resource instances, including those created with count or for_each.
Lists unique resource types and their occurrences.
Identifies providers used in the configuration.
Usage: Run the script with the path to the Terraform state file as an argument to receive a structured summary of the managed resources.

`extract_resource_type_stats.py`:

Purpose: Generates statistics on resource types within a Terraform state file.
Features:
Parses the state file to identify all resource types.
Counts the number of instances for each resource type.
Provides a summary of resource distribution.
Usage: Execute the script with the Terraform state file as input to obtain a breakdown of resource types and their instance counts.

`temporary_intended_resources.py`:

Purpose: Identifies resources in a Terraform state file that are intended to be temporary, based on specific naming conventions.
Features:
Searches for resource names containing keywords like "demo", "test", "temp", "tmp", and "example".
Generates a list of these resources for review.
Assists in managing and cleaning up ephemeral resources.
Usage: Run the script with the state file as an argument to receive a list of resources that match the temporary naming patterns.
These scripts are designed to assist in analyzing and managing resources within Terraform state files, providing insights into resource utilization and aiding in the identification of temporary or test resources.


## Terraform Resource Extractor (`terraform_resource_extractor.py`)
The `terraform_resource_extractor.py` script is a **Terraform state analysis tool** that extracts, counts, and aggregates **managed resources** from a Terraform state (`.tfstate`) file. It helps Terraform users inspect **resource instances, unique resource types, and provider details** in a structured format.

### 🛠 Features
- **Extract managed resources** from a Terraform state file.
- **Count total resource instances** (including those created with `count` or `for_each`).
- **List unique resource types** (e.g., `aws_instance`, `aws_s3_bucket`).
- **Aggregate and summarize resources** to provide insights.
- **Supports debugging mode** to compare instance counts with `jq`.

---

### 📦 Installation Requirements
This script requires **Python 3.x** and the `pandas` library. Install the dependencies using:

```bash
pip install pandas

## Terraform Resource Extractor (`terraform_resource_extractor.py`)

The `terraform_resource_extractor.py` script is a **Terraform state analysis tool** that extracts, counts, and aggregates **managed resources** from a Terraform state (`.tfstate`) file. It helps Terraform users inspect **resource instances, unique resource types, and provider details** in a structured format.

---

### 📦 Installation Requirements

This script requires **Python 3.x** and the `pandas` library. Install the dependencies using:

```bash
pip install pandas
```

---

## 🚀 Usage

Run the script using Python and specify the Terraform state file (`.tfstate`) you want to analyze.

---

### 1️⃣ Extract & Display Managed Resources (Default Mode)

```bash
python terraform_resource_extractor.py -f terraform.tfstate
```

🔹 **Outputs a structured list** of all managed resources, including:

- **Module** (Terraform module where the resource is defined)
- **Resource Type** (e.g., `aws_instance`, `google_compute_instance`)
- **Resource Name** (Terraform name of the resource)
- **Provider** (Cloud provider)
- **Instance Count** (Number of instances)

---

### 2️⃣ 🔹 **Recommended Mode: Show Aggregated Resource Summary (**\`\`**)**

```bash
python terraform_resource_extractor.py -f terraform.tfstate -A
```

✅ **Recommended for most users** as it provides **high-level insights**.\
🔹 **Outputs summary statistics**, including:

- **Total instances**
- **Total unique resources**
- **Unique resource types**
- **Most common resource types & names**

#### Example Output:

```
📊 Aggregate Information:
🔹 Total number of resource instances: 47
🔹 Total number of unique resources: 12
🔹 Total number of unique resource types: 5

🔹 Unique Resource Types:
aws_instance          23
aws_s3_bucket         12
aws_security_group     8
...

🔹 Unique Resource Names:
web_server            10
db_instance            5
...
```

---

### 3️⃣ Count Total Resource Instances (`-n`)

```bash
python terraform_resource_extractor.py -f terraform.tfstate -n
```

🔹 **Outputs only the total number** of resource instances across all types.

#### Example Output:

```
Total number of resource instances: 47
```

---

### 4️⃣ Enable Debug Mode (`-d`)

```bash
python terraform_resource_extractor.py -f terraform.tfstate -n -d
```

🔹 **Compares Python output with ****\`\`**** expected values**, ensuring accuracy.

#### Example Output:

```
🔍 DEBUG: Expected jq output (from Python simulation): 47
🔍 DEBUG: Total resource instances counted (flattened): 47
```

---

### 5️⃣ Exclude HashiCorp-Related Resources (`-H`)

```bash
python terraform_resource_extractor.py -f terraform.tfstate -H
```

🔹 **Excludes resources related to HashiCorp services** (e.g., `tfe_`, `vault_`).

---

### 6️⃣ Only Show HashiCorp-Related Resources (`-Ho`)

```bash
python terraform_resource_extractor.py -f terraform.tfstate -Ho
```

🔹 **Filters to show only HashiCorp-managed resources** (e.g., `tfe_`, `vault_`).

---

### 7️⃣ Group Resources by Module & Type (`-G`)

```bash
python terraform_resource_extractor.py -f terraform.tfstate -G
```

🔹 **Outputs a grouped view** of resources, organized by:

- **Module**
- **Resource Type**
- **Resource Name**
- **Provider**

#### Example Output:

```
📊 Grouped Resource Information:
Module         Resource Type        Resource Name     Provider              Instance Count
------------------------------------------------------------------------------------------------
root           aws_instance         web_server       aws                   3
module.db      aws_rds_instance     database         aws                   2
module.network aws_vpc              vpc_main         aws                   1
...
```

---

### 8️⃣ Save Extracted Data to a CSV File

```bash
python terraform_resource_extractor.py -f terraform.tfstate -o output.csv
```

🔹 Saves the extracted resource list to a **CSV file** for further analysis.

---



## 📝 Example: Comparing with jq

The script's **total instance count** should match the following `jq` command:

```bash
cat terraform.tfstate | jq '[ .resources[] | select(.mode == "managed") | select(.type == "terraform_data" or .type == "null_resource" | not) | .instances | flatten[] ] | length'
```

Use the `-d` flag to **validate Terraform state parsing**.

---

## 💡 When to Use This Script?

✅ **Understanding Terraform resource structure** in a large state file.\
✅ **Verifying instance counts** before applying changes.\
✅ **Detecting duplicate or unnecessary resources**.\
✅ **Comparing Terraform infrastructure** across deployments.\
✅ **Exporting Terraform resource inventory for audits and reporting.**


