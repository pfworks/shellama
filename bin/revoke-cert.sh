#!/bin/bash
# Revoke a client certificate

if [ -z "$1" ]; then
    echo "Usage: $0 <cert-file>"
    exit 1
fi

CERT_FILE=$1
CERT_DIR="./certs"

if [ ! -f "$CERT_FILE" ]; then
    echo "Error: Certificate file not found: $CERT_FILE"
    exit 1
fi

echo "Revoking certificate: $CERT_FILE"

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

openssl ca -config $CERT_DIR/ca.conf -revoke $CERT_FILE -keyfile $CERT_DIR/ca-key.pem \
    -cert $CERT_DIR/ca-cert.pem

echo "Regenerating CRL..."
openssl ca -config $CERT_DIR/ca.conf -gencrl -keyfile $CERT_DIR/ca-key.pem \
    -cert $CERT_DIR/ca-cert.pem -out $CERT_DIR/crl.pem

echo "Certificate revoked. Updated CRL: $CERT_DIR/crl.pem"
echo "Deploy updated crl.pem to all servers and restart services."
