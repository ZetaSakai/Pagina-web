# Security Configuration - New Era Games

## Web Application Firewall (WAF) - Cloudflare

### Setup Instructions

1. **Configure DNS with Cloudflare**:
   - Create a Cloudflare account (free tier is sufficient)
   - Add your domain to Cloudflare
   - Update your domain's nameservers to point to Cloudflare
   - Enable the proxy (orange cloud) for your DNS records

2. **Configure UFW Firewall**:
   ```bash
   cd /app/Pagina-web/security
   sudo ./cloudflare_ufw_setup.sh
   ```

3. **Verify Firewall Status**:
   ```bash
   sudo ufw status verbose
   ```

## Security Features Implemented

### 1. Rate Limiting (Flask-Limiter)
- Login: 10 requests per minute
- Register: 5 requests per minute  
- Donations: 3 requests per minute
- Game publishing: 10 requests per hour

### 2. CSRF Protection (Flask-WTF)
- All POST forms now include CSRF tokens
- Session cookies configured with SameSite=Lax

### 3. Secure Download Authorization
- `/game/<id>/download-file` now requires:
  - User authentication
  - Proof of ownership (creator, admin, or purchaser)
  - Returns 403 Forbidden for unauthorized access

### 4. Session Security
- `SESSION_COOKIE_SECURE = True` (HTTPS only)
- `SESSION_COOKIE_HTTPONLY = True` (no JavaScript access)
- `SESSION_COOKIE_SAMESITE = 'Lax'` (CSRF protection)
- Session timeout: 1 hour

### 5. Environment Variables
- All secrets moved to `.env` file
- `.env` is excluded from git via `.gitignore`
- Use `.env.example` as a template

## Files Cleaned Up

The following sensitive files have been removed from the project:
- `*.key` (private keys)
- `*.pem` (certificates)
- `*.sql` (database dumps)
- `project_backup*.zip` (backups)

## Next Steps

1. **Rotate all exposed credentials** if they were previously committed to git
2. **Update `.env`** with strong, randomly generated secrets
3. **Enable Cloudflare WAF rules** in the Cloudflare dashboard
4. **Review and test** all security changes

## Cloudflare WAF Rules to Configure

In the Cloudflare Dashboard, configure these rules:

1. **WAF Custom Rules**:
   - Block SQL injection attempts
   - Block XSS attempts
   - Challenge suspicious bots

2. **Rate Limiting**:
   - 100 requests/minute per IP (adjust as needed)

3. **Firewall Rules**:
   - Block countries if your audience is regional
   - Challenge unknown browsers
