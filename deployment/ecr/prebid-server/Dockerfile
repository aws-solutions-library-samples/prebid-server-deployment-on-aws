# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0


# ------------------------------------------------------------------------------------------------------------------------------------------------------
# PURPOSE:
#  This Dockerfile is designed to build a Docker image for the Prebid Server Java application by cloning the repository,
#  building the application using Maven, and setting up the necessary configuration and scripts to run the application inside the container on aws.
# -------------------------------------------------------------------------------------------------------------------------------------------------------
# USAGE:
#  For instructions on how to build this Dockerfile locally, please refer to the README.md file in the current directory.
# -------------------------------------------------------------------------------------------------------------------------------------------------------

# Build stage
FROM public.ecr.aws/docker/library/alpine:3.22.1 AS build

# Install required dependencies
RUN wget -O /etc/apk/keys/amazoncorretto.rsa.pub https://apk.corretto.aws/amazoncorretto.rsa.pub && \
    echo "https://apk.corretto.aws/" >> /etc/apk/repositories && \
    apk update && \
    apk add --no-cache \
        amazon-corretto-21 \
        maven=3.9.9-r0 \
        git \
        jq \
        binutils

# Set JAVA_HOME
ENV JAVA_HOME=/usr/lib/jvm/java-21-amazon-corretto
ENV PATH="${JAVA_HOME}/bin:${PATH}"

# Create custom JRE
RUN $JAVA_HOME/bin/jlink \
    --add-modules java.base,java.logging,java.xml,java.naming,java.desktop,java.management,java.security.jgss,java.instrument,jdk.unsupported,\
java.net.http,java.security.sasl,jdk.naming.dns,jdk.crypto.ec,jdk.security.auth \
    --strip-debug \
    --no-man-pages \
    --no-header-files \
    --compress=2 \
    --output /custom-java-runtime

# Copy source build configuration file
COPY docker-build-config.json docker-build-config.json

# Clone and build in single layer to reduce size
RUN git clone --single-branch --branch master --depth 1 https://github.com/prebid/prebid-server-java.git && \
    cd prebid-server-java && \
    git fetch origin --tags && \
    git checkout $(jq -r .GIT_TAG_VERSION ../docker-build-config.json) && \
    mvn clean package $(jq -r .MVN_CLI_OPTIONS ../docker-build-config.json) && \
    rm -rf ~/.m2/ && rm -rf /tmp/*

# Deploy image
FROM public.ecr.aws/docker/library/alpine:3.22.1 AS deploy
WORKDIR /prebid-server-java

# Copy only the minimal required files
COPY --from=build /prebid-server-java/target/*.jar ./target/
COPY --from=build /prebid-server-java/sample ./sample
COPY --from=build /custom-java-runtime /usr/lib/jvm/java-custom
COPY --chmod=755 bootstrap.sh ../bootstrap.sh

# Set up Java environment and create necessary symlinks
ENV JAVA_HOME=/usr/lib/jvm/java-custom

ENV PATH="${JAVA_HOME}/bin:${PATH}"
RUN mkdir -p /usr/bin && \
    ln -s ${JAVA_HOME}/bin/java /usr/bin/java && \
    ln -s ${JAVA_HOME}/bin/jps /usr/bin/jps

# Install only required packages in single layer
RUN apk --no-cache add curl aws-cli bind-tools && \
    rm -rf /var/cache/apk/*

# Set JVM options for DNS resolution
ENV JAVA_OPTS="\
    -Dvertx.disableDnsResolver=true \
    -Djava.net.preferIPv4Stack=true \
    -Dnetworkaddress.cache.ttl=60 \
    -Dnetworkaddress.cache.negative.ttl=10 \
    -Dsun.net.inetaddr.ttl=60 \
    -Dvertx.nettyDnsResolverRefreshInterval=60 \
    -Dhttps.protocols=TLSv1.2,TLSv1.3 \
    -Djavax.net.ssl.trustStoreType=PKCS12 \
    -Dcom.sun.jndi.ldap.object.disableEndpointIdentification=true \
    -Djdk.tls.client.protocols=TLSv1.2,TLSv1.3"

# Expose ports for the Prebid Server Java application
EXPOSE 8080 8060

# Set the entrypoint to execute the bootstrap script
ENTRYPOINT ["sh", "../bootstrap.sh"]