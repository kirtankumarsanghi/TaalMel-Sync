import { useEffect, useRef, useState } from "react";
import { AlertCircle, Camera, Check, RefreshCw, SwitchCamera, X } from "lucide-react";

type CameraCaptureProps = {
  onCapture: (file: File) => void;
  onClose: () => void;
  title?: string;
};

export default function CameraCapture({
  onCapture,
  onClose,
  title = "Take a photo of the document",
}: CameraCaptureProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const fallbackInputRef = useRef<HTMLInputElement>(null);

  const [hasWebcam, setHasWebcam] = useState(true);
  const [permissionError, setPermissionError] = useState<string | null>(null);
  const [facingMode, setFacingMode] = useState<"environment" | "user">("environment");
  const [capturedBlob, setCapturedBlob] = useState<Blob | null>(null);
  const [capturedUrl, setCapturedUrl] = useState<string | null>(null);
  const [loadingCamera, setLoadingCamera] = useState(true);

  // Start webcam stream
  useEffect(() => {
    let active = true;

    async function initCamera() {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        setHasWebcam(false);
        setLoadingCamera(false);
        return;
      }

      setLoadingCamera(true);
      setPermissionError(null);

      // Stop any existing stream
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((track) => track.stop());
        streamRef.current = null;
      }

      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: {
            facingMode: { ideal: facingMode },
            width: { ideal: 1920 },
            height: { ideal: 1080 },
          },
          audio: false,
        });

        if (!active) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }

        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          await videoRef.current.play().catch(() => undefined);
        }
      } catch (err) {
        if (!active) return;
        const msg =
          err instanceof Error && err.name === "NotAllowedError"
            ? "Camera permission was denied. You can allow camera access in your browser settings or select an image file."
            : "Could not access the camera. You can use the device camera file picker instead.";
        setPermissionError(msg);
      } finally {
        if (active) setLoadingCamera(false);
      }
    }

    if (!capturedBlob) {
      void initCamera();
    }

    return () => {
      active = false;
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((track) => track.stop());
        streamRef.current = null;
      }
    };
  }, [facingMode, capturedBlob]);

  // Clean up object URLs
  useEffect(() => {
    return () => {
      if (capturedUrl) {
        URL.revokeObjectURL(capturedUrl);
      }
    };
  }, [capturedUrl]);

  function takeSnapshot() {
    if (!videoRef.current) return;
    const video = videoRef.current;
    const width = video.videoWidth || 1280;
    const height = video.videoHeight || 720;

    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    ctx.drawImage(video, 0, 0, width, height);
    canvas.toBlob(
      (blob) => {
        if (!blob) return;
        setCapturedBlob(blob);
        const url = URL.createObjectURL(blob);
        setCapturedUrl(url);

        // Stop live stream while reviewing photo
        if (streamRef.current) {
          streamRef.current.getTracks().forEach((track) => track.stop());
          streamRef.current = null;
        }
      },
      "image/jpeg",
      0.92,
    );
  }

  function retake() {
    if (capturedUrl) URL.revokeObjectURL(capturedUrl);
    setCapturedUrl(null);
    setCapturedBlob(null);
  }

  function confirmPhoto() {
    if (!capturedBlob) return;
    const filename = `capture-${Date.now()}.jpg`;
    const file = new File([capturedBlob], filename, { type: "image/jpeg" });
    onCapture(file);
    onClose();
  }

  function handleFallbackFile(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (file) {
      onCapture(file);
      onClose();
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm">
      <div className="relative flex max-h-[92vh] w-full max-w-[620px] flex-col overflow-hidden rounded-2xl bg-paper shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-ink/10 px-5 py-3.5">
          <div className="flex items-center gap-2">
            <Camera className="h-4 w-4 text-ink/60" strokeWidth={1.8} />
            <h3 className="font-dm text-[16px] font-medium tracking-[-0.02em] text-ink">
              {title}
            </h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-ink/40 transition-colors hover:bg-ink/5 hover:text-ink"
            aria-label="Close"
          >
            <X className="h-4 w-4" strokeWidth={1.8} />
          </button>
        </div>

        {/* Viewport */}
        <div className="relative flex min-h-[320px] flex-1 items-center justify-center bg-black">
          {capturedUrl ? (
            <img
              src={capturedUrl}
              alt="Captured document"
              className="max-h-[65vh] w-full object-contain"
            />
          ) : hasWebcam && !permissionError ? (
            <>
              <video
                ref={videoRef}
                playsInline
                autoPlay
                muted
                className="max-h-[65vh] w-full object-contain"
              />
              {loadingCamera && (
                <div className="absolute inset-0 flex items-center justify-center bg-black/60">
                  <RefreshCw className="h-6 w-6 animate-spin text-white/70" />
                </div>
              )}
            </>
          ) : (
            <div className="p-8 text-center text-white">
              <AlertCircle className="mx-auto h-8 w-8 text-amber-400" strokeWidth={1.7} />
              <p className="mt-3 font-dm text-[16px] font-medium">Camera not available</p>
              <p className="mx-auto mt-1 max-w-[340px] font-inter text-[12.5px] leading-relaxed text-white/70">
                {permissionError ??
                  "Your browser does not permit live camera streaming in this tab."}
              </p>
              <button
                type="button"
                onClick={() => fallbackInputRef.current?.click()}
                className="mt-4 inline-flex items-center gap-2 rounded-lg bg-white px-4 py-2 font-inter text-[13px] font-medium text-ink transition-opacity hover:opacity-90"
              >
                <Camera className="h-4 w-4" />
                Use phone/system camera
              </button>
            </div>
          )}

          {/* Hidden input with capture="environment" for direct mobile camera capture fallback */}
          <input
            ref={fallbackInputRef}
            type="file"
            accept="image/*"
            capture="environment"
            className="hidden"
            onChange={handleFallbackFile}
          />
        </div>

        {/* Footer controls */}
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-ink/10 bg-paper px-5 py-3.5">
          {capturedUrl ? (
            <>
              <button
                type="button"
                onClick={retake}
                className="rounded-md border border-ink/15 bg-white px-3.5 py-2 font-inter text-[13px] font-medium text-ink transition-colors hover:bg-ink/[0.04]"
              >
                Retake
              </button>
              <button
                type="button"
                onClick={confirmPhoto}
                className="flex items-center gap-2 rounded-md bg-ink px-4 py-2 font-inter text-[13px] font-medium text-white transition-opacity hover:opacity-90"
              >
                <Check className="h-4 w-4" strokeWidth={2} />
                Use photo
              </button>
            </>
          ) : (
            <>
              <div className="flex items-center gap-2">
                {hasWebcam && !permissionError && (
                  <button
                    type="button"
                    onClick={() =>
                      setFacingMode((m) => (m === "environment" ? "user" : "environment"))
                    }
                    className="flex items-center gap-1.5 rounded-md border border-ink/15 bg-white px-2.5 py-1.5 font-inter text-[12px] text-ink/70 hover:text-ink"
                    title="Flip camera"
                  >
                    <SwitchCamera className="h-3.5 w-3.5" />
                    Flip
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => fallbackInputRef.current?.click()}
                  className="rounded-md px-2 py-1 font-inter text-[12px] text-ink/50 underline underline-offset-2 hover:text-ink"
                >
                  Choose file / mobile camera
                </button>
              </div>

              {hasWebcam && !permissionError && (
                <button
                  type="button"
                  onClick={takeSnapshot}
                  className="flex items-center gap-2 rounded-md bg-ink px-4 py-2 font-inter text-[13px] font-medium text-white transition-opacity hover:opacity-90"
                >
                  <Camera className="h-4 w-4" strokeWidth={1.8} />
                  Capture
                </button>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
