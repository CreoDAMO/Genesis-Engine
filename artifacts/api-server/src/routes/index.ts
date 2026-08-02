import { Router, type IRouter } from "express";
import healthRouter from "./health";
import genesisRouter from "./genesis.js";

const router: IRouter = Router();

router.use(healthRouter);
router.use("/genesis", genesisRouter);

export default router;
