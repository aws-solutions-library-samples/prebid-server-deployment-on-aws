package org.prebid.server.analytics.reporter.psdoa;

import io.vertx.core.Future;
import org.prebid.server.analytics.AnalyticsReporter;
import org.prebid.server.analytics.model.AmpEvent;
import org.prebid.server.analytics.model.AuctionEvent;
import org.prebid.server.analytics.model.CookieSyncEvent;
import org.prebid.server.analytics.model.NotificationEvent;
import org.prebid.server.analytics.model.SetuidEvent;
import org.prebid.server.analytics.model.VideoEvent;
import org.prebid.server.auction.model.AuctionContext;
import org.prebid.server.analytics.reporter.psdoa.model.PsdoaEventType;
import org.prebid.server.analytics.reporter.psdoa.model.PsdoaBidResponse;
import org.prebid.server.analytics.reporter.psdoa.model.PsdoaBidRequest;
import org.prebid.server.analytics.reporter.psdoa.model.PsdoaBidderStatus;
import org.prebid.server.analytics.reporter.psdoa.model.PsdoaEvent;
import org.prebid.server.analytics.reporter.psdoa.model.PsdoaUserSync;
import org.prebid.server.model.HttpRequestContext;
import org.prebid.server.json.JacksonMapper;
import org.prebid.server.log.Logger;
import org.prebid.server.log.LoggerFactory;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.stream.Collectors;

public class PsdoaAnalyticsReporter implements AnalyticsReporter {

    private static final Logger logger = LoggerFactory.getLogger(PsdoaAnalyticsReporter.class);
    private final JacksonMapper jacksonMapper;

    public PsdoaAnalyticsReporter(JacksonMapper jacksonMapper) {
        this.jacksonMapper = Objects.requireNonNull(jacksonMapper);
    }

    @Override
    public <T> Future<Void> processEvent(T event) {
        try {
            logger.debug("Processing analytics event: {}", event);

            final PsdoaEvent.PsdoaEventBuilder eventBuilder = PsdoaEvent.builder();
            final HttpRequestContext httpContext = getHttpContext(event);

            switch (event) {
                case AmpEvent ampEvent -> {
                    final Map<String, String> targeting = new HashMap<>();
                    final AuctionContext ampAuctionContext = ampEvent.getAuctionContext();
                    ampEvent.getTargeting().forEach((key, value) ->
                            targeting.put(key, value.asText()));

                    eventBuilder
                            .type(PsdoaEventType.AMP)
                            .bidRequest(jacksonMapper.mapper().convertValue(
                                ampAuctionContext.getBidRequest(),
                                PsdoaBidRequest.class))
                            .bidResponse(jacksonMapper.mapper().convertValue(
                                    ampEvent.getBidResponse(),
                                    PsdoaBidResponse.class))
                            .targeting(targeting)
                            .origin(ampEvent.getOrigin());
                }
                case AuctionEvent auctionEvent -> {
                    final AuctionContext auctionContext = auctionEvent.getAuctionContext();
                    eventBuilder
                            .type(PsdoaEventType.AUCTION)
                            .bidRequest(jacksonMapper.mapper().convertValue(
                                auctionContext.getBidRequest(),
                                PsdoaBidRequest.class))
                            .bidResponse(jacksonMapper.mapper().convertValue(
                                    auctionEvent.getBidResponse(),
                                    PsdoaBidResponse.class));
                }
                case CookieSyncEvent cookieSyncEvent -> {
                    final List<PsdoaBidderStatus> bidderStatus = cookieSyncEvent.getBidderStatus().stream()
                            .map(status -> PsdoaBidderStatus.builder()
                                    .bidder(status.getBidder())
                                    .noCookie(status.getNoCookie())
                                    .usersync(PsdoaUserSync.builder()
                                            .url(status.getUsersync().getUrl())
                                            .type(status.getUsersync().getType().toString())
                                            .build())
                                    .build())
                            .collect(Collectors.toList());
                    eventBuilder
                            .type(PsdoaEventType.COOKIE_SYNC)
                            .bidderStatus(bidderStatus);
                }
                case NotificationEvent notificationEvent -> {
                    eventBuilder
                            .type(PsdoaEventType.EVENT)
                            .bidId(notificationEvent.getBidId())
                            .timestamp(notificationEvent.getTimestamp())
                            .notificationType(notificationEvent.getType().toString())
                            .bidder(notificationEvent.getBidder())
                            .integration(notificationEvent.getIntegration());
                }
                case SetuidEvent setuidEvent -> {
                    eventBuilder
                            .type(PsdoaEventType.SETUID)
                            .bidder(setuidEvent.getBidder())
                            .uid(setuidEvent.getUid())
                            .success(setuidEvent.getSuccess());
                }
                case VideoEvent videoEvent -> {
                    final AuctionContext videoAuctionContext = videoEvent.getAuctionContext();
                    eventBuilder
                            .type(PsdoaEventType.VIDEO)
                            .bidRequest(jacksonMapper.mapper().convertValue(
                                videoAuctionContext.getBidRequest(),
                                PsdoaBidRequest.class))
                            .bidResponse(jacksonMapper.mapper().convertValue(
                                    videoEvent.getBidResponse(),
                                    PsdoaBidResponse.class));
                }
                case null, default -> {
                    logger.debug("Handling unknown event type: {}", event);
                    eventBuilder
                            .type(PsdoaEventType.UNKNOWN)
                            .unknownEvent(jacksonMapper.mapper().valueToTree(event));
                }
            }

            if (httpContext != null) {
                final Map<String, String> headers = new HashMap<>();
                httpContext.getHeaders().entries().forEach(entry ->
                        headers.put(entry.getKey(), entry.getValue()));

                final Map<String, String> queryParams = new HashMap<>();
                if (httpContext.getQueryParams() != null) {
                    httpContext.getQueryParams().entries().forEach(entry ->
                            queryParams.put(entry.getKey(), entry.getValue()));
                }

                eventBuilder
                        .headers(headers)
                        .queryParams(queryParams)
                        .remoteHost(httpContext.getRemoteHost())
                        .body(httpContext.getBody())
                        .scheme(httpContext.getScheme())
                        .httpMethod(httpContext.getHttpMethod().name())
                        .absoluteUri(httpContext.getAbsoluteUri())
                        .refererHeader(headers.get("Referer"))
                        .userAgent(headers.get("User-Agent"));
            }

            final PsdoaEvent psdoaEvent = eventBuilder.build();
            logger.info(jacksonMapper.encodeToString(psdoaEvent));

        } catch (Exception e) {
            logger.error("Error processing analytics event: {}", e.getMessage(), e);
        }

        return Future.succeededFuture();
    }

    private <T> HttpRequestContext getHttpContext(T event) {
        return switch (event) {
            case AmpEvent ampEvent -> ampEvent.getHttpContext();
            case AuctionEvent auctionEvent -> auctionEvent.getHttpContext();
            case NotificationEvent notificationEvent -> notificationEvent.getHttpContext();
            case VideoEvent videoEvent -> videoEvent.getHttpContext();
            default -> null;
        };
    }

    @Override
    public int vendorId() {
        return 0;
    }

    @Override
    public String name() {
        return "psdoaAnalytics";
    }
}
