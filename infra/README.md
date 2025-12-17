# Valence Pod Infrastructure

Ansible playbooks for deploying the Valence pod to a Digital Ocean droplet.

## Architecture

The pod runs:
- **Synapse** - Matrix homeserver for chat interface
- **PostgreSQL 16 + pgvector** - Database with vector similarity search
- **VKB** - Valence Knowledge Base MCP server
- **Nginx** - Reverse proxy with SSL termination

## Prerequisites

1. A Digital Ocean account with API token
2. A domain pointed to your droplet's IP
3. SSH key pair for droplet access

## Required Environment Variables

```bash
# Droplet IP (set after creation)
export VALENCE_POD_IP="your.droplet.ip"

# Domain for Matrix homeserver
export VALENCE_DOMAIN="your.domain.com"

# Database password (generate a strong one)
export VALENCE_DB_PASSWORD="$(openssl rand -base64 32)"

# Email for Let's Encrypt SSL certificates
export LETSENCRYPT_EMAIL="your@email.com"

# Matrix bot password
export VALENCE_BOT_PASSWORD="$(openssl rand -base64 32)"

# API keys for VKB service
export OPENAI_API_KEY="sk-..."
export ANTHROPIC_API_KEY="sk-ant-..."
```

## Deployment Steps

### 1. Create the Droplet

```bash
# Install doctl if needed
# brew install doctl  # macOS
# snap install doctl  # Linux

# Authenticate
doctl auth init

# Create droplet
doctl compute droplet create valence-pod \
  --image ubuntu-24-04-x64 \
  --size s-2vcpu-4gb \
  --region nyc1 \
  --ssh-keys $(doctl compute ssh-key list --format ID --no-header | head -1) \
  --wait

# Get the IP
export VALENCE_POD_IP=$(doctl compute droplet get valence-pod --format PublicIPv4 --no-header)
```

### 2. Configure DNS

Point your domain to the droplet IP. Required records:
- `A` record: `your.domain.com` -> `VALENCE_POD_IP`
- `A` record: `matrix.your.domain.com` -> `VALENCE_POD_IP` (optional)

Wait for DNS propagation before proceeding.

### 3. Generate SSH Key (if needed)

```bash
ssh-keygen -t ed25519 -f ~/.ssh/valence_pod -N ""
# Add public key to droplet
doctl compute droplet ssh valence-pod --ssh-key-path ~/.ssh/valence_pod
```

### 4. Run the Playbook

```bash
cd infra

# Install Ansible if needed
pip install ansible

# Run deployment
ansible-playbook -i inventory.yml site.yml
```

### 5. Authenticate Claude Code (Manual Step)

```bash
ssh -i ~/.ssh/valence_pod valence@$VALENCE_POD_IP
claude  # Follow OAuth prompts
```

### 6. Connect Element Client

1. Download Element: https://element.io/download
2. Choose "Sign in"
3. Click "Edit" homeserver
4. Enter: `https://your.domain.com`
5. Sign in with admin credentials

## Security

The playbook configures:
- UFW firewall (only SSH, HTTP, HTTPS, Matrix federation)
- SSH key-only authentication
- fail2ban for SSH protection
- systemd security hardening for services
- SSL via Let's Encrypt

## Roles

| Role | Purpose |
|------|---------|
| security | UFW, SSH hardening, fail2ban, valence user |
| common | Base packages, Valence repo clone, Claude Code |
| postgresql | PostgreSQL 16, pgvector extension, database |
| synapse | Matrix homeserver, nginx, SSL certificates |
| vkb | VKB MCP service, Matrix bot user |

## Troubleshooting

### Check service status
```bash
sudo systemctl status matrix-synapse
sudo systemctl status vkb
sudo systemctl status postgresql
sudo systemctl status nginx
```

### View logs
```bash
sudo journalctl -u vkb -f
sudo journalctl -u matrix-synapse -f
```

### Test Matrix federation
```bash
curl https://your.domain.com/.well-known/matrix/server
curl https://your.domain.com/.well-known/matrix/client
```
