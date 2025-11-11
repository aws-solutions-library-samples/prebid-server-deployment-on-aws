package org.prebid.server.analytics.reporter.psdoa.model;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.fasterxml.jackson.databind.JsonNode;
import lombok.Builder;
import lombok.Value;

import java.util.List;

@Value
@Builder
@JsonIgnoreProperties(ignoreUnknown = true)
public class PsdoaBidRequest {

    @JsonProperty("id")
    String id;

    @JsonProperty("imp")
    List<JsonNode> imp;

    @JsonProperty("site")
    JsonNode site;

    @JsonProperty("app")
    JsonNode app;

    @JsonProperty("device")
    JsonNode device;

    @JsonProperty("user")
    JsonNode user;

    @JsonProperty("test")
    Integer test;

    @JsonProperty("at")
    Integer at;

    @JsonProperty("tmax")
    Integer tmax;

    @JsonProperty("cur")
    List<String> cur;

    @JsonProperty("bcat")
    List<String> bcat;

    @JsonProperty("badv")
    List<String> badv;

    @JsonProperty("bapp")
    List<String> bapp;

    @JsonProperty("source")
    JsonNode source;

    @JsonProperty("regs")
    JsonNode regs;

    @JsonProperty("metric")
    List<JsonNode> metric;

    @JsonProperty("ext")
    JsonNode ext;
}
