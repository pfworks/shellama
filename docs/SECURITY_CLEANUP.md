# Security Cleanup Instructions

## CRITICAL: Remove Sensitive Files from Git

The repository currently contains sensitive files that should NOT be in version control:
- SSL/TLS certificates and private keys in `certs/` directory
- Server inventory files with hostnames
- Backend configuration files

## Steps to Clean Up

### 1. Remove sensitive files from git history

```bash
cd /home/rory/github/ansible-tools

# Remove files from git (but keep local copies)
git rm -r --cached certs/
git rm --cached inventory.ini inventory-frontend.ini backends.json

# Commit the removal
git commit -m "Remove sensitive files from repository"

# Push changes
git push
```

### 2. Create your local configuration files

```bash
# Copy example files to create your actual config
cp inventory.ini.example inventory.ini
cp inventory-frontend.ini.example inventory-frontend.ini
cp backends.json.example backends.json

# Edit these files with your actual server information
# These files are now in .gitignore and won't be committed
```

### 3. Regenerate certificates

Since the old certificates are now exposed in git history, regenerate them:

```bash
# Remove old certificates
rm -rf certs/

# Generate new certificates
./generate-certs.sh

# Generate user certificates as needed
./generate-user-cert.sh <username>
```

### 4. Redeploy with new certificates

```bash
# Copy files to deployment machine
scp -r * root@ansible.corp.ooma.com:/tmp/ansible-tools/

# SSH to deployment machine
ssh root@ansible.corp.ooma.com

# Deploy backends
cd /tmp/ansible-tools
ansible-playbook -i inventory.ini deploy.yml

# Deploy frontend
ansible-playbook -i inventory-frontend.ini deploy-frontend.yml
```

### 5. Set Infisical token

On each backend server:

```bash
systemctl edit ansible-ollama
```

Add:
```
[Service]
Environment="INFISICAL_TOKEN=your-token-here"
```

Then restart:
```bash
systemctl restart ansible-ollama
```

## Files Now Protected

The following are now in `.gitignore` and won't be committed:
- `certs/` - All certificates and keys
- `inventory.ini` - Backend server list
- `inventory-frontend.ini` - Frontend server list
- `backends.json` - Backend URLs

## What Gets Committed

Only these template files are in git:
- `inventory.ini.example`
- `inventory-frontend.ini.example`
- `backends.json.example`

Each deployment environment should create their own copies from these templates.
