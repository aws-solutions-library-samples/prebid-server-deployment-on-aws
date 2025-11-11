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
public class PsdoaBidResponse {

    @JsonProperty("id")
    String id;

    @JsonProperty("seatbid")
    List<JsonNode> seatbid;

    @JsonProperty("bidid")
    String bidid;

    @JsonProperty("cur")
    String cur;

    @JsonProperty("customdata")
    String customdata;

    @JsonProperty("nbr")
    Integer nbr;

    @JsonProperty("ext")
    JsonNode ext;
}
