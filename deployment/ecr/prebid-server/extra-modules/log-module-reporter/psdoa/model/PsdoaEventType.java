package org.prebid.server.analytics.reporter.psdoa.model;

import com.fasterxml.jackson.annotation.JsonValue;
import lombok.Getter;
import lombok.RequiredArgsConstructor;

@Getter
@RequiredArgsConstructor
public enum PsdoaEventType {

    AUCTION("/openrtb2/auction"),
    AMP("/openrtb2/amp"),
    VIDEO("/openrtb2/video"),
    COOKIE_SYNC("/cookie_sync"),
    SETUID("/setuid"),
    EVENT("/event"),
    UNKNOWN("unknown");

    @JsonValue
    private final String path;

    public static PsdoaEventType fromPath(String path) {
        for (PsdoaEventType type : values()) {
            if (type.getPath().equals(path)) {
                return type;
            }
        }
        return UNKNOWN;
    }
}
