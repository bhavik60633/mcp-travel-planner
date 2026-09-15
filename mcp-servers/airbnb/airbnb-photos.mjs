// Switches on the Airbnb MCP server's listing photo field (TP-04 A1, A2).
//
// The server's search answer leaves photos out: the field is commented out in its code
// (`// contextualPictures: { picture: true }`). Yori switches it back on as the server loads, only for the
// version checked. The downloaded package stays unchanged, and any other version runs as it is.

export const PINNED_VERSION = "0.3.0";

const PHOTO_FIELD_OFF = /\/\/\s*contextualPictures:\s*\{\s*\/\/\s*picture:\s*true\s*\/\/\s*\}/;

export function switchOnPhotos(source, version) {
  if (version !== PINNED_VERSION) {
    return { source, enabled: false, reason: `the Airbnb server is version ${version}, and photos were only checked with ${PINNED_VERSION}` };
  }
  if (!PHOTO_FIELD_OFF.test(source)) {
    return { source, enabled: false, reason: `the photo field wasn't found in the Airbnb server ${version}` };
  }
  return { source: source.replace(PHOTO_FIELD_OFF, "contextualPictures: { picture: true }"), enabled: true, reason: null };
}
