#import "NVEEffectSession.h"

NVEFrameGeometry NVEFrameGeometryMakeUpstreamOriented(BOOL mirror) {
    NVEFrameGeometry geometry = {
        .policy = NVEFrameGeometryPolicyUpstreamOriented,
        .mirror = mirror,
        .imageOrientation = AVCaptureVideoOrientationPortrait,
        .displayRotation = 0,
    };
    return geometry;
}

NVEFrameGeometry NVEFrameGeometryMakeCaptureMirrored(void) {
    NVEFrameGeometry geometry = {
        .policy = NVEFrameGeometryPolicyCaptureMirrored,
        .mirror = NO,
        .imageOrientation = AVCaptureVideoOrientationPortrait,
        .displayRotation = 0,
    };
    return geometry;
}

NVEFrameGeometry NVEFrameGeometryMakeExplicitSDKMetadata(
    BOOL mirror,
    AVCaptureVideoOrientation imageOrientation,
    float displayRotation
) {
    NVEFrameGeometry geometry = {
        .policy = NVEFrameGeometryPolicyExplicitSDKMetadata,
        .mirror = mirror,
        .imageOrientation = imageOrientation,
        .displayRotation = displayRotation,
    };
    return geometry;
}

static NSString *const NVEEffectSessionErrorDomain = @"NVEEffectSession";

typedef NS_ENUM(NSInteger, NVEEffectSessionErrorCode) {
    NVEEffectSessionErrorInvalidPath = 1,
    NVEEffectSessionErrorLicense = 2,
    NVEEffectSessionErrorModel = 3,
    NVEEffectSessionErrorInvalidMode = 4,
    NVEEffectSessionErrorRender = 5,
    NVEEffectSessionErrorMissingOutput = 6,
};

@interface NVEEffectSession ()
@property(nonatomic, strong, readwrite) NveEffectKit *effectKit;
@property(nonatomic, assign) NveRenderMode renderMode;
@end

@implementation NVEEffectSession

static BOOL sLicenseVerified = NO;
static BOOL sPrepared = NO;
static NSMutableSet<NSNumber *> *sInitializedModels;

+ (void)setError:(NSError **)error code:(NVEEffectSessionErrorCode)code message:(NSString *)message {
    if (error) {
        *error = [NSError errorWithDomain:NVEEffectSessionErrorDomain
                                     code:code
                                 userInfo:@{NSLocalizedDescriptionKey: message}];
    }
}

+ (BOOL)prepareWithLicensePath:(NSString *)licensePath
                    modelPaths:(NSDictionary<NSNumber *, NSString *> *)modelPaths
                         error:(NSError **)error {
    @synchronized(self) {
        sPrepared = NO;
        NSFileManager *files = NSFileManager.defaultManager;
        if (!sLicenseVerified) {
            if (licensePath.length == 0 || ![files fileExistsAtPath:licensePath]) {
                [self setError:error code:NVEEffectSessionErrorInvalidPath message:@"NveEffectKit license file is missing."];
                return NO;
            }
            // The license must be verified before the first shareInstance call.
            if (![NveEffectKit verifySdkLicenseFile:licensePath]) {
                [self setError:error code:NVEEffectSessionErrorLicense message:@"NveEffectKit license verification failed."];
                return NO;
            }
            sLicenseVerified = YES;
            sInitializedModels = [NSMutableSet set];
        }

        NSArray<NSNumber *> *orderedTypes = [modelPaths.allKeys sortedArrayUsingSelector:@selector(compare:)];
        for (NSNumber *boxedType in orderedTypes) {
            if ([sInitializedModels containsObject:boxedType]) {
                continue;
            }
            NSString *path = modelPaths[boxedType];
            if (path.length == 0 || ![files fileExistsAtPath:path]) {
                [self setError:error
                           code:NVEEffectSessionErrorInvalidPath
                        message:[NSString stringWithFormat:@"Model is missing for type %@.", boxedType]];
                return NO;
            }
            BOOL initialized = [NveEffectKit initHumanDetection:(NveDetectionModelType)boxedType.integerValue
                                                      modelPath:path
                                                licenseFilePath:nil];
            if (!initialized) {
                [self setError:error
                           code:NVEEffectSessionErrorModel
                        message:[NSString stringWithFormat:@"Model initialization failed for type %@.", boxedType]];
                return NO;
            }
            [sInitializedModels addObject:boxedType];
        }
        sPrepared = YES;
        return YES;
    }
}

- (instancetype)initWithRenderMode:(NveRenderMode)renderMode error:(NSError **)error {
    @synchronized(NVEEffectSession.class) {
        if (!sPrepared) {
            [NVEEffectSession setError:error code:NVEEffectSessionErrorLicense message:@"Call prepareWithLicensePath:modelPaths:error: before creating a session."];
            return nil;
        }
    }
    self = [super init];
    if (self) {
        _renderMode = renderMode;
        _effectKit = [NveEffectKit shareInstance];
    }
    return self;
}

- (BOOL)consumeInput:(NveRenderInput *)input
       consumeOutput:(void (^)(NveRenderOutput *output))consumeOutput
               error:(NSError **)error {
    NSParameterAssert(consumeOutput != nil);
    NveRenderOutput *output = [self.effectKit renderEffect:input];
    if (!output) {
        [NVEEffectSession setError:error code:NVEEffectSessionErrorRender message:@"NveEffectKit returned no output."];
        return NO;
    }

    NveRenderError renderError = output.errorCode;
    BOOL succeeded = renderError == NveRenderError_noError;
    if (!succeeded) {
        [self.effectKit recycleOutput:output];
        [NVEEffectSession setError:error
                              code:NVEEffectSessionErrorRender
                           message:[NSString stringWithFormat:@"NveEffectKit render failed (%ld).", (long)renderError]];
        return NO;
    }
    BOOL hasPayload = self.renderMode == NveRenderMode_buffer_buffer
        ? output.pixelBuffer != nil
        : output.texture != nil && output.texture.textureId != 0;
    if (!hasPayload) {
        [self.effectKit recycleOutput:output];
        [NVEEffectSession setError:error code:NVEEffectSessionErrorMissingOutput message:@"NveEffectKit returned no payload for the configured render mode."];
        return NO;
    }
    @try {
        consumeOutput(output);
    } @finally {
        // This must run on success and error paths. Do not retain output.texture or output.pixelBuffer.
        [self.effectKit recycleOutput:output];
    }
    return succeeded;
}

- (BOOL)renderPixelBuffer:(CVPixelBufferRef)pixelBuffer
                 geometry:(NVEFrameGeometry)geometry
        isFromFrontCamera:(BOOL)isFromFrontCamera
                timestamp:(NSNumber *)timestamp
             outputFormat:(NvePixelFormatType)outputFormat
       outputTextureLayout:(NveTextureLayout)outputTextureLayout
       overlayInputBuffer:(BOOL)overlayInputBuffer
            consumeOutput:(void (^)(NveRenderOutput *output))consumeOutput
                    error:(NSError **)error {
    if (self.renderMode == NveRenderMode_texture_texture) {
        [NVEEffectSession setError:error code:NVEEffectSessionErrorInvalidMode message:@"Use renderTexture: for texture -> texture."];
        return NO;
    }

    NveImageBuffer *image = [NveImageBuffer new];
    image.pixelBuffer = pixelBuffer;
    image.mirror = geometry.mirror;
    if (geometry.policy == NVEFrameGeometryPolicyExplicitSDKMetadata) {
        image.imageOrientation = geometry.imageOrientation;
        image.displayRotation = geometry.displayRotation;
    }

    NveRenderConfig *config = [NveRenderConfig new];
    config.renderMode = self.renderMode;
    config.outputFormatType = outputFormat;
    config.outputTextureLayout = outputTextureLayout;
    config.overlayInputBuffer = overlayInputBuffer;
    config.isFromFrontCamera = isFromFrontCamera;

    NveRenderInput *input = [NveRenderInput new];
    input.imageBuffer = image;
    input.config = config;
    // Leave nil unless the vendor contract defines the timestamp unit and timebase.
    if (timestamp) {
        input.renderTimestamp = timestamp.longLongValue;
    }
    return [self consumeInput:input consumeOutput:consumeOutput error:error];
}

- (BOOL)renderTexture:(GLuint)textureId
                  size:(CGSize)size
         textureLayout:(NveTextureLayout)textureLayout
  detectionPixelBuffer:(CVPixelBufferRef)detectionPixelBuffer
              geometry:(NVEFrameGeometry)geometry
     isFromFrontCamera:(BOOL)isFromFrontCamera
             timestamp:(NSNumber *)timestamp
   outputTextureLayout:(NveTextureLayout)outputTextureLayout
         consumeOutput:(void (^)(NveRenderOutput *output))consumeOutput
                 error:(NSError **)error {
    if (self.renderMode != NveRenderMode_texture_texture) {
        [NVEEffectSession setError:error code:NVEEffectSessionErrorInvalidMode message:@"Session is not configured for texture -> texture."];
        return NO;
    }

    NveTexture *texture = [NveTexture new];
    texture.textureId = textureId;
    texture.size = size;
    texture.textureLayout = textureLayout;

    NveImageBuffer *image = nil;
    if (detectionPixelBuffer) {
        image = [NveImageBuffer new];
        image.pixelBuffer = detectionPixelBuffer;
        image.mirror = geometry.mirror;
        if (geometry.policy == NVEFrameGeometryPolicyExplicitSDKMetadata) {
            image.imageOrientation = geometry.imageOrientation;
            image.displayRotation = geometry.displayRotation;
        }
    }

    NveRenderConfig *config = [NveRenderConfig new];
    config.renderMode = NveRenderMode_texture_texture;
    config.outputTextureLayout = outputTextureLayout;
    config.isFromFrontCamera = isFromFrontCamera;

    NveRenderInput *input = [NveRenderInput new];
    input.texture = texture;
    input.imageBuffer = image;
    input.config = config;
    // Leave nil unless the vendor contract defines the timestamp unit and timebase.
    if (timestamp) {
        input.renderTimestamp = timestamp.longLongValue;
    }
    return [self consumeInput:input consumeOutput:consumeOutput error:error];
}

+ (void)destroySharedInstance {
    @synchronized(self) {
        [NveEffectKit destroyInstance];
        sLicenseVerified = NO;
        sPrepared = NO;
        [sInitializedModels removeAllObjects];
        sInitializedModels = nil;
    }
}

@end
