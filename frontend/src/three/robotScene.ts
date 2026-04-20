import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { ColladaLoader } from "three/examples/jsm/loaders/ColladaLoader.js";
import { OBJLoader } from "three/examples/jsm/loaders/OBJLoader.js";
import URDFLoader from "urdf-loader";

import type { RobotState, RuntimeProfile } from "../types/protocol";

interface ChainFrames {
  worldFrame: THREE.Object3D;
  eeFrame: THREE.Object3D | null;
}

export class RobotScene {
  private readonly scene: THREE.Scene;
  private readonly camera: THREE.PerspectiveCamera;
  private readonly renderer: THREE.WebGLRenderer;
  private readonly robotRoot: THREE.Group;
  private readonly mount: HTMLElement;
  private readonly profile: RuntimeProfile;
  private readonly controls: OrbitControls;
  /** Per-chain frame helpers, keyed by chainId. */
  private readonly chainFrames: Map<string, ChainFrames> = new Map();
  private activeChainIds: Set<string> | null = null;
  private urdfRobot: any = null;
  private pendingState: RobotState | null = null;
  private disposed = false;

  public constructor(mount: HTMLElement, urdfUrl: string, profile: RuntimeProfile) {
    this.mount = mount;
    this.profile = profile;
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color("#f6f8fa");
    this.scene.up.set(0, 0, 1);

    this.camera = new THREE.PerspectiveCamera(50, mount.clientWidth / Math.max(1, mount.clientHeight), 0.01, 100);
    this.camera.up.set(0, 0, 1);
    this.camera.position.set(1.2, -1.2, 1.0);
    this.camera.lookAt(0, 0.5, 0);

    const hemi = new THREE.HemisphereLight(0xf6f8fa, 0xd0d7de, 1.0);
    this.scene.add(hemi);
    const dir = new THREE.DirectionalLight(0xffffff, 1.1);
    dir.position.set(2, 3, 1);
    this.scene.add(dir);

    this.robotRoot = new THREE.Group();
    this.scene.add(this.robotRoot);

    const grid = new THREE.GridHelper(4, 24, 0x9aa4b2, 0xe6ebf1);
    grid.rotateX(Math.PI / 2);
    this.scene.add(grid);

    // Build per-chain world frames (initially hidden; shown by setActiveChains).
    const chainIds = Object.keys(profile.tipLinks ?? {});
    for (const chainId of chainIds) {
      const worldFrame = this.createBoldFrame(0.45, 0.012);
      worldFrame.visible = false;
      this.scene.add(worldFrame);
      this.chainFrames.set(chainId, { worldFrame, eeFrame: null });
    }
    // Fallback if no chains: single always-visible world frame.
    if (chainIds.length === 0) {
      const worldFrame = this.createBoldFrame(0.45, 0.012);
      this.scene.add(worldFrame);
      this.chainFrames.set("__default__", { worldFrame, eeFrame: null });
    }

    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(window.devicePixelRatio);
    this.renderer.setSize(mount.clientWidth, mount.clientHeight);
    mount.appendChild(this.renderer.domElement);

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;
    this.controls.target.set(0, 0, 0.45);
    this.controls.update();

    if (urdfUrl) {
      const loader = new URDFLoader() as URDFLoader & {
        loadMeshCb?: (
          path: string,
          manager: THREE.LoadingManager,
          onComplete: (obj: THREE.Object3D | null, err?: Error) => void,
        ) => void;
      };
      loader.loadMeshCb = (path: string, manager: THREE.LoadingManager, onComplete) => {
        if (path.toLowerCase().endsWith(".obj")) {
          const objLoader = new OBJLoader(manager);
          objLoader.load(
            path,
            (obj) => onComplete(obj),
            undefined,
            () => onComplete(null, new Error(`failed to load mesh: ${path}`)),
          );
          return;
        }
        if (path.toLowerCase().endsWith(".dae")) {
          const colladaLoader = new ColladaLoader(manager);
          colladaLoader.load(
            path,
            (collada) => onComplete(collada.scene),
            undefined,
            () => onComplete(null, new Error(`failed to load mesh: ${path}`)),
          );
          return;
        }
        onComplete(null, new Error(`unsupported mesh format: ${path}`));
      };
      loader.load(
        urdfUrl,
        (robot) => {
          this.urdfRobot = robot;
          this.robotRoot.add(robot as THREE.Object3D);
          this.attachEndEffectorFrames();
          this.applyActiveChainVisibility();
          if (this.pendingState) {
            this.update(this.pendingState);
            this.pendingState = null;
          }
        },
        undefined,
        () => {
          this.addFallbackMesh();
        },
      );
    } else {
      this.addFallbackMesh();
    }

    this.renderLoop();
  }

  /**
   * Set which chains are "active" (their world and EE frames will be shown).
   * Pass null to show all frames (default when no teach panels present).
   */
  public setActiveChains(chainIds: string[] | null): void {
    this.activeChainIds = chainIds ? new Set(chainIds) : null;
    this.applyActiveChainVisibility();
  }

  public update(_state: RobotState): void {
    if (!this.urdfRobot) {
      this.pendingState = _state;
      return;
    }

    const chainMap = this.profile.jointMap ?? {};
    const chainOffsets = this.profile.jointOffsetsDeg ?? {};
    const chains = _state.chains ?? {};
    for (const [chainId, chainState] of Object.entries(chains)) {
      const offsets = chainOffsets[chainId] ?? [];
      const renderedAngles = chainState.joints.map((item, index) => item.angle_deg + Number(offsets[index] ?? 0));
      this.applyMappedJoints(
        renderedAngles,
        chainMap[chainId] ?? [],
      );
    }
  }

  private applyMappedJoints(jointAnglesDeg: number[], jointNames: string[]): void {
    const limit = Math.min(jointAnglesDeg.length, jointNames.length);
    for (let i = 0; i < limit; i += 1) {
      const name = jointNames[i];
      const valueRad = (jointAnglesDeg[i] * Math.PI) / 180.0;
      try {
        if (this.urdfRobot && typeof this.urdfRobot.setJointValue === "function") {
          this.urdfRobot.setJointValue(name, valueRad);
        }
      } catch {
        // Ignore unknown or invalid joint names in profile mapping.
      }
    }
  }

  public resize(): void {
    const width = this.mount.clientWidth;
    const height = Math.max(1, this.mount.clientHeight);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height);
  }

  public dispose(): void {
    this.disposed = true;
    this.pendingState = null;
    this.controls.dispose();
    this.renderer.dispose();
    this.mount.removeChild(this.renderer.domElement);
  }

  private applyActiveChainVisibility(): void {
    for (const [chainId, frames] of this.chainFrames.entries()) {
      const active = chainId === "__default__" || this.activeChainIds === null || this.activeChainIds.has(chainId);
      frames.worldFrame.visible = active;
      if (frames.eeFrame) {
        frames.eeFrame.visible = active;
      }
    }
  }

  private addFallbackMesh(): void {
    const fallback = new THREE.Mesh(
      new THREE.BoxGeometry(0.4, 0.6, 0.3),
      new THREE.MeshStandardMaterial({ color: "#2e4057" }),
    );
    fallback.position.y = 0.3;
    this.robotRoot.add(fallback);
  }

  private attachEndEffectorFrames(): void {
    if (!this.urdfRobot) {
      return;
    }

    const tipLinks = this.profile.tipLinks ?? {};
    const links = (this.urdfRobot.links ?? {}) as Record<string, THREE.Object3D | undefined>;

    // Remove any previously attached EE frames.
    for (const frames of this.chainFrames.values()) {
      if (frames.eeFrame) {
        frames.eeFrame.removeFromParent();
        frames.eeFrame = null;
      }
    }

    for (const [chainId, tipLink] of Object.entries(tipLinks)) {
      if (!tipLink) {
        continue;
      }
      const link = links[tipLink];
      if (!link) {
        continue;
      }
      const eeFrame = this.createBoldFrame(0.45, 0.012);
      link.add(eeFrame);
      const existing = this.chainFrames.get(chainId);
      if (existing) {
        existing.eeFrame = eeFrame;
      }
    }
  }

  private createBoldFrame(size: number, shaftRadius: number): THREE.Object3D {
    const group = new THREE.Group();
    const shaftLength = size * 0.78;
    const headLength = size - shaftLength;
    const headRadius = shaftRadius * 2.2;
    const sourceAxis = new THREE.Vector3(0, 1, 0);

    const addAxis = (dir: THREE.Vector3, color: number): void => {
      const material = new THREE.MeshBasicMaterial({ color });
      const rotation = new THREE.Quaternion().setFromUnitVectors(sourceAxis, dir.clone().normalize());

      const shaft = new THREE.Mesh(new THREE.CylinderGeometry(shaftRadius, shaftRadius, shaftLength, 10), material);
      shaft.quaternion.copy(rotation);
      shaft.position.copy(dir).multiplyScalar(shaftLength * 0.5);
      group.add(shaft);

      const head = new THREE.Mesh(new THREE.ConeGeometry(headRadius, headLength, 12), material);
      head.quaternion.copy(rotation);
      head.position.copy(dir).multiplyScalar(shaftLength + headLength * 0.5);
      group.add(head);
    };

    addAxis(new THREE.Vector3(1, 0, 0), 0xe64545);
    addAxis(new THREE.Vector3(0, 1, 0), 0x2f9e44);
    addAxis(new THREE.Vector3(0, 0, 1), 0x228be6);
    return group;
  }

  private readonly renderLoop = (): void => {
    if (this.disposed) {
      return;
    }
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
    requestAnimationFrame(this.renderLoop);
  };
}
