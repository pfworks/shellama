#!/bin/bash
# Generate user client certificate

if [ -z "$1" ]; then
    echo "Usage: $0 <username>"
    exit 1
fi

USERNAME=$1
CERT_DIR="./certs"

echo "Generating certificate for user: $USERNAME"

openssl genrsa -out $CERT_DIR/$USERNAME-key.pem 4096
openssl req -new -key $CERT_DIR/$USERNAME-key.pem -out $CERT_DIR/$USERNAME-req.pem \
    -subj "/C=US/ST=CA/L=SanJose/O=Ooma/CN=$USERNAME"
openssl x509 -req -days 365 -in $CERT_DIR/$USERNAME-req.pem -CA $CERT_DIR/ca-cert.pem \
    -CAkey $CERT_DIR/ca-key.pem -CAcreateserial -out $CERT_DIR/$USERNAME-cert.pem

chmod 600 $CERT_DIR/$USERNAME-key.pem
chmod 644 $CERT_DIR/$USERNAME-cert.pem

echo "Certificate created:"
echo "  $CERT_DIR/$USERNAME-cert.pem"
echo "  $CERT_DIR/$USERNAME-key.pem"
echo ""
echo "Distribute these files to the user along with ca-cert.pem"
