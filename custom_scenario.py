from typing import Callable, Dict

import torch
import random
from torch import Tensor
from vmas import render_interactively
from vmas.simulator.core import Agent, Landmark, Sphere, World, Entity
from vmas.simulator.heuristic_policy import BaseHeuristicPolicy
from vmas.simulator.scenario import BaseScenario
from vmas.simulator.sensors import Lidar
from vmas.simulator.utils import Color, X, Y, ScenarioUtils

class CustomScenario(BaseScenario):
    def make_world(self, batch_dim: int, device: torch.device, **kwargs):    
        self.pos_shaping_factor = kwargs.get("pos_shaping_factor", 10.0)
        self.dist_shaping_factor = kwargs.get("dist_shaping_factor", 10.0)
        self.agent_radius = kwargs.get("agent_radius", 0.1)
        self.n_agents = kwargs.get("n_agents", 1)

        self.min_distance_between_entities = self.agent_radius * 2 + 0.05
        self.world_semidim = 1

        self.obstacle_collision_reward = -10
        self.agent_collision_reward = -1
        self.desired_distance = 0.15
        self.min_collision_distance = 0.005
        self.collective_reward = 0

        world = World(batch_dim, device)

        goal = Landmark(
            name=f"goal",
            collide=False,
            color=Color.BLACK,
        )
        world.add_landmark(goal)

        for i in range(1):

            obstacle = Landmark(
                name="obstacle",
                collide=True,
                color=Color.RED
            )

            world.add_landmark(obstacle)
        
        for i in range(self.n_agents):
            agent = Agent(
                name=f"agent{i}",
                collide=True,
                color=Color.GREEN,
                render_action=True,
            )
            agent.pos_rew = torch.zeros(batch_dim, device=device)
            agent.collision_rew = agent.pos_rew.clone()
            agent.goal = goal
            world.add_agent(agent)

        self.pos_rew = torch.zeros(batch_dim, device=device)
        self.final_rew = self.pos_rew.clone()

        return world

    def reset_world_at(self, env_index: int = None):
        # Definisce i limiti dell'area in cui posizionare gli agenti
        position_range = (-1, 1)

        # Genera posizioni casuali per i landmarks
        random_landmark_position = (position_range[1] - position_range[0]) * torch.rand(
            (1, 2), device=self.world.device, dtype=torch.float32
        ) + position_range[0]

        # Setta le posizioni dei landmarks alle posizioni casuali generate
        self.world.landmarks[0].set_pos(
            torch.tensor([-0.8, 0.8]), #random_landmark_position, 
            batch_index=env_index,
        ) 

        self.world.landmarks[1].set_pos(
            torch.tensor([-0.1, 0.1]),
            batch_index=env_index,
        ) 

        """ self.world.landmarks[2].set_pos(
            torch.tensor([0.1, 0.5]), 
            batch_index=env_index,
        ) """ 

        # Genera posizioni casuali all'interno dell'area definita

        central_position = torch.tensor([[0.6, -0.6]])

        """ central_position = (position_range[1] - position_range[0]) * torch.rand(
            (1, 2), device=self.world.device, dtype=torch.float32
        ) + position_range[0] """

        offsets = torch.tensor([
            [-0.15, 0.0],  # sinistra
            [0.15, 0.0],   # destra
            [0.0, 0.15],   # sopra
            [0.0, -0.15],   # sotto
        ], device='cpu', dtype=torch.float32)

        """ [-0.15, -0.15],
            [0.15, -0.15],
            [0.15, 0.15],
            [-0.15, 0.15], """

        # Calcolare le posizioni degli altri agenti
        surrounding_positions = central_position + offsets

        # Concatenare la posizione centrale con le posizioni circostanti
        all__agents_positions = torch.cat((central_position, surrounding_positions), dim=0)

        #random_agent_positions = torch.tensor([[0.0, 0.0], [-0.1, 0.0], [0.1, 0.0], [0.0, -0.1], [0.0, 0.1]])

        # Setta le posizioni degli agenti alle posizioni casuali generate
        for i, agent in enumerate(self.world.agents):
            agent.set_pos(
                all__agents_positions[i],
                batch_index=env_index,
            )

            if env_index is None:
                agent.previous_distance_to_goal = (
                    torch.linalg.vector_norm(
                        agent.state.pos - agent.goal.state.pos,
                        dim=1,
                    )
                    * self.pos_shaping_factor
                )

                agent.previous_distance_to_agents = (
                    torch.stack(
                        [
                            torch.linalg.vector_norm(
                                agent.state.pos - a.state.pos, dim=-1
                            )
                            for a in self.world.agents
                            if a != agent
                        ],
                        dim=1,
                    )
                    - self.desired_distance
                ).pow(2).mean(-1) * self.dist_shaping_factor
            else:
                agent.previous_distance_to_goal[env_index] = (
                    torch.linalg.vector_norm(
                        agent.state.pos[env_index] - agent.goal.state.pos[env_index]
                    )
                    * self.pos_shaping_factor
                )

                agent.previous_distance_to_agents[env_index] = (
                    torch.stack(
                        [
                            torch.linalg.vector_norm(
                                agent.state.pos[env_index] - a.state.pos[env_index]
                            )
                            for a in self.world.agents
                            if a != agent
                        ],
                        dim=0,
                    )
                    - self.desired_distance
                ).pow(2).mean(-1) * self.dist_shaping_factor
        

    def reward(self, agent):
        if agent == self.world.agents[0]:
            self.collective_reward = 0

            for a in self.world.agents:
                self.collective_reward += self.distance_to_goal_reward(a) + self.distance_to_agents_reward(a) + self.agent_avoidance_reward(a) + self.obstacle_avoidance_reward(a)

        return self.collective_reward
    
    def distance_to_goal_reward(self, agent: Agent):
        agent.distance_to_goal = torch.linalg.vector_norm(
            agent.state.pos - agent.goal.state.pos,
            dim=-1,
        )
        agent.on_goal = agent.distance_to_goal < agent.goal.shape.radius 

        shaped_distance_to_goal = agent.distance_to_goal * self.pos_shaping_factor #Distanza attuale tra l'agente e il goal pesandola per shaping_factor
        agent.pos_rew = agent.previous_distance_to_goal - shaped_distance_to_goal #Reward in base alla differenza tra la distanza precedente e quella attuale
        agent.previous_distance_to_goal = shaped_distance_to_goal #Salva la distanza per la prossima iterazione

        reward = agent.pos_rew

        if agent.on_goal:
            reward = reward + 20

        return reward 
    
    def distance_to_agents_reward(self, agent: Agent):
        distance_to_agents = (
            torch.stack(
                [
                    torch.linalg.vector_norm(agent.state.pos - a.state.pos, dim=-1)
                    for a in self.world.agents
                    if a != agent
                ],
                dim=1,
            )
            - self.desired_distance
        ).pow(2).mean(-1) * self.dist_shaping_factor
        agent.dist_rew = agent.previous_distance_to_agents - distance_to_agents
        agent.previous_distance_to_agents = distance_to_agents

        return agent.dist_rew
    
    def obstacle_avoidance_reward(self, agent: Agent):

        for i in range (1,2):
            if self.world.get_distance(agent, self.world.landmarks[i]) <= self.min_collision_distance :
                return self.obstacle_collision_reward

        return 0
    
    def agent_avoidance_reward(self, agent: Agent):
        reward = 0

        reward = sum(
            self.agent_collision_reward for other_agent in self.world.agents
            if agent.name != other_agent.name and self.world.get_distance(agent, other_agent) <= self.min_collision_distance
        )

        return reward

    def observation(self, agent: Agent):
        return torch.cat(
            [
                agent.state.pos,
                agent.state.vel,
                self.world.landmarks[0].state.pos,
                #agent.state.pos - self.world.landmarks[0].state.pos,
            ],
            dim=-1,
        )

    def done(self):
        return torch.zeros(self.world.batch_dim, device=self.world.device, dtype=torch.bool)

    def info(self, agent: Agent):
        return {
            "pos_rew": agent.pos_rew,
            "final_rew": self.final_rew
        }

    
if __name__ == "__main__":
    render_interactively(CustomScenario(), control_two_agents=False)