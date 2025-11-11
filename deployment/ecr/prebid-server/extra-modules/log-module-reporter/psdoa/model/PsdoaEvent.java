package org.prebid.server.analytics.reporter.psdoa.model;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.fasterxml.jackson.databind.JsonNode;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Value;

import java.util.List;
import java.util.Map;

@Builder
@AllArgsConstructor
@Value
public class PsdoaEvent {

    @JsonProperty("type")
    PsdoaEventType type;

    @JsonProperty("headers")
    Map<String, String> headers;

    @JsonProperty("queryParams")
    Map<String, String> queryParams;

    @JsonProperty("remoteHost")
    String remoteHost;

    @JsonProperty("httpMethod")
    String httpMethod;

    @JsonProperty("absoluteUri")
    String absoluteUri;

    @JsonProperty("scheme")
    String scheme;

    @JsonProperty("body")
    String body;

    @JsonProperty("refererHeader")
    String refererHeader;

    @JsonProperty("userAgent")
    String userAgent;

    @JsonProperty("bidResponse")
    PsdoaBidResponse bidResponse;

    @JsonProperty("bidRequest")
    PsdoaBidRequest bidRequest;

    @JsonProperty("targeting")
    Map<String, String> targeting;

    @JsonProperty("origin")
    String origin;

    @JsonProperty("bidderStatus")
    List<PsdoaBidderStatus> bidderStatus;

    @JsonProperty("bidId")
    String bidId;

    @JsonProperty("timestamp")
    Long timestamp;

    @JsonProperty("notificationType")
    String notificationType;

    @JsonProperty("bidder")
    String bidder;

    @JsonProperty("integration")
    String integration;

    @JsonProperty("uid")
    String uid;

    @JsonProperty("success")
    Boolean success;

    @JsonProperty("unknownEvent")
    JsonNode unknownEvent;
}
