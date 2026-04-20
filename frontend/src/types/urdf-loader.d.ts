declare module "urdf-loader" {
  export default class URDFLoader {
    load(
      url: string,
      onLoad: (robot: unknown) => void,
      onProgress?: (event: ProgressEvent<EventTarget>) => void,
      onError?: (error: unknown) => void,
    ): void;
  }
}
