// Prebid.js header bidding implementation
var pbjs = pbjs || {};
pbjs.que = pbjs.que || [];

// Read the Prebid Server endpoint from the "prebidserver" query parameter.
// Falls back to a relative path for local development or same-origin setups.
var PREBID_SERVER_ENDPOINT = (function() {
    var params = new URLSearchParams(window.location.search);
    var ep = params.get("prebidserver");
    return ep ? "https://" + ep + "/openrtb2/auction" : "/openrtb2/auction";
})();

// Define ad units
var adUnits = [
    {
        code: 'banner_imp_1',
        mediaTypes: {
            banner: {
                sizes: [[300, 250]]
            }
        },
        bids: [
            {
                bidder: 'amt',
                params: {
                    placementId: "13144370",
                    bidFloor: 1,
                    bidCeiling: 100000,
                }
            }
        ]
    },
    {
        code: 'banner_imp_2',
        mediaTypes: {
            banner: {
                sizes: [[300, 250]]
            }
        },
        bids: [
            {
                bidder: 'amt',
                params: {
                    placementId: "13144371",
                    bidFloor: 1,
                    bidCeiling: 100000,
                }
            }
        ]
    },
    {
        code: 'outstream_video_imp_1',
        mediaTypes: {
            video: {
                context: "outstream",
                playerSize: [360, 360],
                mimes: ["video/mp4"],
            }
        },
        bids: [
            {
                bidder: 'amt',
                params: {
                    placementId: "13144370",
                    bidFloor: 1,
                    bidCeiling: 100000,
                }
            }
        ],
        renderer: {
            url: 'https://cdn.jsdelivr.net/npm/in-renderer-js@1/dist/in-renderer.umd.min.js',
            render: function(bid) {
                var inRenderer = new window.InRenderer();
                // Pass configuration to constrain the size
                inRenderer.render("outstream_video_imp_1", bid, {
                    width: 360,
                    height: 360
                });
            }
        }
    },
    {
        code: 'instream_video_imp_1',
        mediaTypes: {
            video: {
                context: "instream",
                playerSize: [640, 480],
                mimes: ["video/mp4"],
                protocols: [1, 2, 3, 4, 5, 6, 7, 8],
                playbackmethod: [2],
                skip: 1
            }
        },
        bids: [
            {
                bidder: 'amt',
                params: {
                    placementId: "13144370",
                    bidFloor: 1,
                    bidCeiling: 100000,
                }
            }
        ]
    }
];

// Configure Prebid Server
var prebidServerConfig = {
    debug: true,
    s2sConfig: [
        {
            accountId: '12345',
            bidders: ['amt'],
            adapter: 'prebidServer',
            enabled: true,
            endpoint: PREBID_SERVER_ENDPOINT,
            extPrebid: {
                cache: {
                    vastxml: {returnCreative: false}
                }
            }
        }
    ],
    consentManagement: {
        gdpr: {
            cmpApi: 'static', // Use 'static' to provide manual data
            timeout: 0,         // No need to wait for a CMP
            defaultGdprScope: false, // Forces regs.ext.gdpr=0 if not found
            consentData: {
                getTCData: {
                    gdprApplies: false, // Explicitly set to false
                    tcString: ""   // TC string not needed when gdprApplies is false
                }
            }
        }
    }
};

// Render winning bid in iframe
function renderOne(winningBid) {
    console.log("Rendering winning bid:", winningBid);
    if (winningBid && winningBid.adId) {
        var div = document.getElementById(winningBid.adUnitCode);
        if (div) {
            const iframe = document.createElement('iframe');
            iframe.scrolling = 'no';
            iframe.frameBorder = '0';
            iframe.marginHeight = '0';
            iframe.marginWidth = '0';
            iframe.name = `prebid_ads_iframe_${winningBid.adUnitCode}`;
            iframe.title = '3rd party ad content';
            iframe.sandbox.add(
                'allow-forms',
                'allow-popups',
                'allow-popups-to-escape-sandbox',
                'allow-same-origin',
                'allow-scripts',
                'allow-top-navigation-by-user-activation'
            );
            iframe.setAttribute('aria-label', 'Advertisement');
            iframe.style.border = '0';
            iframe.style.margin = '0';
            iframe.style.overflow = 'hidden';

            div.appendChild(iframe);

            const iframeDoc = iframe.contentWindow.document;
            pbjs.renderAd(iframeDoc, winningBid.adId);

            // Add normalize CSS to iframe
            const normalizeCss = `/*! normalize.css v8.0.1 | MIT License | github.com/necolas/normalize.css */button,hr,input{overflow:visible}progress,sub,sup{vertical-align:baseline}[type=checkbox],[type=radio],legend{box-sizing:border-box;padding:0}html{line-height:1.15;-webkit-text-size-adjust:100%}body{margin:0}details,main{display:block}h1{font-size:2em;margin:.67em 0}hr{box-sizing:content-box;height:0}code,kbd,pre,samp{font-family:monospace,monospace;font-size:1em}a{background-color:transparent}abbr[title]{border-bottom:none;text-decoration:underline;text-decoration:underline dotted}b,strong{font-weight:bolder}small{font-size:80%}sub,sup{font-size:75%;line-height:0;position:relative}sub{bottom:-.25em}sup{top:-.5em}img{border-style:none}button,input,optgroup,select,textarea{font-family:inherit;font-size:100%;line-height:1.15;margin:0}button,select{text-transform:none}[type=button],[type=reset],[type=submit],button{-webkit-appearance:button}[type=button]::-moz-focus-inner,[type=reset]::-moz-focus-inner,[type=submit]::-moz-focus-inner,button::-moz-focus-inner{border-style:none;padding:0}[type=button]:-moz-focusring,[type=reset]:-moz-focusring,[type=submit]:-moz-focusring,button:-moz-focusring{outline:ButtonText dotted 1px}fieldset{padding:.35em .75em .625em}legend{color:inherit;display:table;max-width:100%;white-space:normal}textarea{overflow:auto}[type=number]::-webkit-inner-spin-button,[type=number]::-webkit-outer-spin-button{height:auto}[type=search]{-webkit-appearance:textfield;outline-offset:-2px}[type=search]::-webkit-search-decoration{-webkit-appearance:none}::-webkit-file-upload-button{-webkit-appearance:button;font:inherit}summary{display:list-item}[hidden],template{display:none}`;
            
            const iframeStyle = iframeDoc.createElement('style');
            iframeStyle.appendChild(iframeDoc.createTextNode(normalizeCss));
            iframeDoc.head.appendChild(iframeStyle);
        }
    }
}

// Render all winning bids

function renderAllAdUnits() {
    console.log("Getting winning bids");
    var winners = pbjs.getHighestCpmBids();
    for (var i = 0; i < winners.length; i++) {
        if (winners[i].adUnitCode === 'instream_video_imp_1') {
            // Handle instream video
            var vastUrl = winners[i].vastUrl;
            invokeVideoPlayer(vastUrl);
        } else {
            // Handle banner and outstream
            renderOne(winners[i]);
        }
    }
}

// Initialize Prebid
pbjs.que.push(function() {
    console.log("Setting Prebid.js config");
    pbjs.setConfig(prebidServerConfig);
});

pbjs.que.push(function() {
    console.log("Adding ad units");
    pbjs.addAdUnits(adUnits);
});

pbjs.que.push(function() {
    console.log("Requesting bids");
    pbjs.requestBids({
        timeout: 5000,
        bidsBackHandler: renderAllAdUnits
    });
});


// Initialize instream video player when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    if (typeof videojs !== 'undefined') {
        var player = videojs('vid1', {
            width: 640,
            height: 480,
            controls: true,
            autoplay: false,
            preload: 'auto',
            sources: [{
                src: "https://vjs.zencdn.net/v/oceans.mp4",
                type: 'video/mp4'
            }]
        });
        console.log('Video.js player initialized');
    }
});

// Invoke video player with VAST
function invokeVideoPlayer(url) {
    console.log("Prebid VAST url = " + url);
    
    var player = videojs("vid1");
    if (player && typeof player.vastClient === 'function') {
        player.vastClient({
            adTagUrl: url,
            playAdAlways: true,
            verbosity: 4,
            autoplay: true
        });
        
        console.log("Prebid VAST tag inserted!");
        player.muted(true);
        player.play();
    } else {
        console.error('vastClient plugin not available');
    }
}
