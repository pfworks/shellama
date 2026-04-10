#!/bin/bash
# Generate SSL certificates for Ansible Tools

set -e

CERT_DIR="./certs"
mkdir -p $CERT_DIR

# Create CA database files for revocation
touch $CERT_DIR/index.txt
echo 1000 > $CERT_DIR/serial
echo 1000 > $CERT_DIR/crlnumber

# Generate CA (Certificate Authority)
echo "Generating CA..."
openssl genrsa -out $CERT_DIR/ca-key.pem 4096
openssl req -new -x509 -days 3650 -key $CERT_DIR/ca-key.pem -out $CERT_DIR/ca-cert.pem \
    -subj "/C=US/ST=CA/L=SanJose/O=Ooma/CN=Ansible-Tools-CA"

# Generate Server Certificate (for frontend and backends)
echo "Generating server certificate..."
cat > $CERT_DIR/server-ext.cnf << EOF
subjectAltName = DNS:*.corp.ooma.com,DNS:ansible.corp.ooma.com,DNS:delvecchio.corp.ooma.com,DNS:oomaai.corp.ooma.com,DNS:nvidia-ollama-1.corp.ooma.com,DNS:localhost
EOF
openssl genrsa -out $CERT_DIR/server-key.pem 4096
openssl req -new -key $CERT_DIR/server-key.pem -out $CERT_DIR/server-req.pem \
    -subj "/C=US/ST=CA/L=SanJose/O=Ooma/CN=*.corp.ooma.com"
openssl x509 -req -days 3650 -in $CERT_DIR/server-req.pem -CA $CERT_DIR/ca-cert.pem \
    -CAkey $CERT_DIR/ca-key.pem -CAcreateserial -out $CERT_DIR/server-cert.pem \
    -extfile $CERT_DIR/server-ext.cnf

# Generate Client Certificate (for frontend-to-backend)
echo "Generating frontend client certificate..."
openssl genrsa -out $CERT_DIR/client-key.pem 4096
openssl req -new -key $CERT_DIR/client-key.pem -out $CERT_DIR/client-req.pem \
    -subj "/C=US/ST=CA/L=SanJose/O=Ooma/CN=ansible-tools-frontend"
openssl x509 -req -days 3650 -in $CERT_DIR/client-req.pem -CA $CERT_DIR/ca-cert.pem \
    -CAkey $CERT_DIR/ca-key.pem -CAcreateserial -out $CERT_DIR/client-cert.pem

# Generate initial empty CRL
echo "Generating CRL..."
cat > $CERT_DIR/ca.conf << EOF
[ ca ]
default_ca = CA_default

[ CA_default ]
dir = $CERT_DIR
database = \$dir/index.txt
serial = \$dir/serial
crlnumber = \$dir/crlnumber
default_crl_days = 30
default_md = sha256
EOF

openssl ca -config $CERT_DIR/ca.conf -gencrl -keyfile $CERT_DIR/ca-key.pem \
    -cert $CERT_DIR/ca-cert.pem -out $CERT_DIR/crl.pem

# Set permissions
chmod 600 $CERT_DIR/*-key.pem
chmod 644 $CERT_DIR/*-cert.pem $CERT_DIR/crl.pem

echo "Certificates generated in $CERT_DIR/"
echo ""
echo "Files created:"
echo "  ca-cert.pem       - CA certificate (distribute to all servers)"
echo "  server-cert.pem   - Server certificate (for frontend/backend)"
echo "  server-key.pem    - Server private key (for frontend/backend)"
echo "  client-cert.pem   - Client certificate (for frontend)"
echo "  client-key.pem    - Client private key (for frontend)"
echo "  crl.pem           - Certificate Revocation List"
echo ""
echo "To generate user certificates, run: ./generate-user-cert.sh <username>"
echo "To revoke a certificate, run: ./revoke-cert.sh <cert-file>"
