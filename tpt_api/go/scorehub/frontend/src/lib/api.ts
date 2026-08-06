import { GetTeams } from "../../wailsjs/go/bindings/TeamBinding"
import type { team } from "../../wailsjs/go/models"

export type Team = team.Team

export const teamApi = {
  list: (): Promise<Team[]> => GetTeams(),
}
