package org.prebid.server.analytics.reporter.psdoa;

import com.fasterxml.jackson.databind.node.ObjectNode;
import io.vertx.core.Future;
import org.junit.Before;
import org.junit.Test;
import org.prebid.server.analytics.model.AuctionEvent;
import org.prebid.server.analytics.model.HttpContext;
import org.prebid.server.json.JacksonMapper;
import org.prebid.server.model.CaseInsensitiveMultiMap;
import org.prebid.server.model.HttpRequestContext;
import org.prebid.server.analytics.reporter.psdoa.PsdoaAnalyticsReporter;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.BDDMockito.given;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;

public class PsdoaAnalyticsReporterTest {

    private PsdoaAnalyticsReporter analyticsReporter;
    private JacksonMapper jacksonMapper;

    @Before
    public void setUp() {
        jacksonMapper = new JacksonMapper();
        analyticsReporter = new PsdoaAnalyticsReporter(jacksonMapper);
    }

    @Test
    public void shouldProcessAuctionEvent() {
        // given
        final CaseInsensitiveMultiMap headers = CaseInsensitiveMultiMap.builder()
                .add("Accept", "*/*")
                .add("Content-Type", "application/json")
                .add("User-Agent", "test-agent")
                .build();

        final ObjectNode bidResponse = jacksonMapper.mapper().createObjectNode()
                .put("id", "test-id")
                .put("bidid", "test-bid-id");

        final AuctionEvent auctionEvent = AuctionEvent.builder()
                .httpContext(HttpRequestContext.builder()
                        .headers(headers)
                        .queryParams(CaseInsensitiveMultiMap.empty())
                        .remoteHost("test-host")
                        .build())
                .bidResponse(bidResponse)
                .build();

        // when
        final Future<Void> future = analyticsReporter.processEvent(auctionEvent);

        // then
        assertThat(future.succeeded()).isTrue();
    }

    @Test
    public void shouldReturnCorrectVendorId() {
        // when and then
        assertThat(analyticsReporter.vendorId()).isEqualTo(0);
    }

    @Test
    public void shouldReturnCorrectAnalyticsReporterName() {
        // when and then
        assertThat(analyticsReporter.name()).isEqualTo("psdoaAnalytics");
    }

    @Test
    public void shouldHandleNullHttpContext() {
        // given
        final ObjectNode bidResponse = jacksonMapper.mapper().createObjectNode()
                .put("id", "test-id");

        final AuctionEvent auctionEvent = AuctionEvent.builder()
                .bidResponse(bidResponse)
                .build();

        // when
        final Future<Void> future = analyticsReporter.processEvent(auctionEvent);

        // then
        assertThat(future.succeeded()).isTrue();
    }

    @Test
    public void shouldHandleEmptyBidResponse() {
        // given
        final AuctionEvent auctionEvent = AuctionEvent.builder()
                .httpContext(HttpRequestContext.builder()
                        .headers(CaseInsensitiveMultiMap.empty())
                        .build())
                .bidResponse(jacksonMapper.mapper().createObjectNode())
                .build();

        // when
        final Future<Void> future = analyticsReporter.processEvent(auctionEvent);

        // then
        assertThat(future.succeeded()).isTrue();
    }

    @Test
    public void shouldHandleNullEvent() {
        // when
        final Future<Void> future = analyticsReporter.processEvent(null);

        // then
        assertThat(future.succeeded()).isTrue();
    }

    @Test
    public void shouldHandleExceptionGracefully() {
        // given
        final JacksonMapper mockMapper = mock(JacksonMapper.class);
        given(mockMapper.encodeToString(any())).willThrow(new RuntimeException("Test exception"));
        
        final PsdoaAnalyticsReporter reporter = new PsdoaAnalyticsReporter(mockMapper);
        final AuctionEvent auctionEvent = AuctionEvent.builder().build();

        // when
        final Future<Void> future = reporter.processEvent(auctionEvent);

        // then
        assertThat(future.succeeded()).isTrue();
    }
}
