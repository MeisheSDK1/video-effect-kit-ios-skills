#import <AVFoundation/AVFoundation.h>
#import <Foundation/Foundation.h>
#import <NveEffectKit/NveEffectKit.h>

NS_ASSUME_NONNULL_BEGIN

typedef NS_ENUM(NSInteger, NVEFrameGeometryPolicy) {
    /// The upstream owner already produced pixels in presentation orientation.
    /// Leave NVE imageOrientation/displayRotation at their SDK defaults.
    NVEFrameGeometryPolicyUpstreamOriented = 0,
    /// A separately audited non-camera contract requires NVE direction metadata.
    NVEFrameGeometryPolicyExplicitSDKMetadata = 1,
    /// A device A/B probe proved NVE mirror output is all zero. The capture
    /// connection already owns mirroring, so NVE mirror remains disabled.
    NVEFrameGeometryPolicyCaptureMirrored = 2,
};

typedef struct {
    NVEFrameGeometryPolicy policy;
    BOOL mirror;
    AVCaptureVideoOrientation imageOrientation;
    float displayRotation;
} NVEFrameGeometry;

FOUNDATION_EXPORT NVEFrameGeometry NVEFrameGeometryMakeUpstreamOriented(BOOL mirror);
FOUNDATION_EXPORT NVEFrameGeometry NVEFrameGeometryMakeCaptureMirrored(void);
FOUNDATION_EXPORT NVEFrameGeometry NVEFrameGeometryMakeExplicitSDKMetadata(
    BOOL mirror,
    AVCaptureVideoOrientation imageOrientation,
    float displayRotation
);

/// A small, UI-agnostic adapter for an existing capture/render pipeline.
/// Output objects are valid only for the duration of `consumeOutput`.
@interface NVEEffectSession : NSObject

@property(nonatomic, strong, readonly) NveEffectKit *effectKit;

/// Must be called before creating a session. Keys are boxed NveDetectionModelType values.
/// Pass only the models required by the selected features.
+ (BOOL)prepareWithLicensePath:(NSString *)licensePath
                    modelPaths:(NSDictionary<NSNumber *, NSString *> *)modelPaths
                         error:(NSError **)error;

- (instancetype)init NS_UNAVAILABLE;
- (nullable instancetype)initWithRenderMode:(NveRenderMode)renderMode
                                      error:(NSError **)error NS_DESIGNATED_INITIALIZER;

/// Supports buffer -> buffer and buffer -> texture.
- (BOOL)renderPixelBuffer:(CVPixelBufferRef)pixelBuffer
                 geometry:(NVEFrameGeometry)geometry
        isFromFrontCamera:(BOOL)isFromFrontCamera
                timestamp:(nullable NSNumber *)timestamp
             outputFormat:(NvePixelFormatType)outputFormat
       outputTextureLayout:(NveTextureLayout)outputTextureLayout
       overlayInputBuffer:(BOOL)overlayInputBuffer
            consumeOutput:(void (^)(NveRenderOutput *output))consumeOutput
                    error:(NSError **)error;

/// Supports texture -> texture. Supply detectionPixelBuffer when enabled effects need face/body detection.
- (BOOL)renderTexture:(GLuint)textureId
                  size:(CGSize)size
         textureLayout:(NveTextureLayout)textureLayout
  detectionPixelBuffer:(nullable CVPixelBufferRef)detectionPixelBuffer
              geometry:(NVEFrameGeometry)geometry
     isFromFrontCamera:(BOOL)isFromFrontCamera
             timestamp:(nullable NSNumber *)timestamp
   outputTextureLayout:(NveTextureLayout)outputTextureLayout
         consumeOutput:(void (^)(NveRenderOutput *output))consumeOutput
                 error:(NSError **)error;

/// Process-wide teardown. Call only after the frame queue has drained and no other owner uses the singleton.
+ (void)destroySharedInstance;

@end

NS_ASSUME_NONNULL_END
