import sys
import os

scenarios_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src', 'scenarios'))
sys.path.insert(0, scenarios_dir)

import random
import time
import torch
from vmas import make_env
from vmas.simulator.core import Agent
from vmas.simulator.utils import save_video
from ray.rllib.algorithms.ppo import PPO
import numpy as np
from vmas.simulator.environment.rllib import VectorEnvWrapper
from cohesion_scenario import CohesionScenario
from go_to_position_scenario import GoToPositionScenario
from flocking_scenario import FlockingScenario

def _get_deterministic_action(agent: Agent, continuous: bool, env):
    if continuous:
        action = -agent.action.u_range_tensor.expand(env.batch_dim, agent.action_size)
    else:
        action = (
            torch.tensor([1], device=env.device, dtype=torch.long)
            .unsqueeze(-1)
            .expand(env.batch_dim, 1)
        )
    return action.clone()


def use_vmas_env(
    render: bool = False,
    save_render: bool = False,
    n_steps: int = 200,
    random_action: bool = False,
    scenario_name: str = "custom_scenario",
    visualize_render: bool = True,
    trainer: PPO = None,
    env_config: dict = None,
):
    assert not (save_render and not render), "To save the video you have to render it"

    env = make_env(
        CohesionScenario(),
        scenario_name = env_config["scenario_name"],
        num_envs=env_config["num_envs"],
        device=env_config["device"],
        continuous_actions=env_config["continuous_actions"],
        dict_spaces=True,
        wrapper=None,
        seed=None,
        # Environment specific variables
        n_agents=env_config["scenario_config"]["n_agents"],
    )
    frame_list = []  # For creating a gif
    init_time = time.time()
    step = 0

    obs_dict = env.reset() #Dictionary that contains all the agents observations
    
    for _ in range(n_steps):
        step += 1
        print(f"Step {step}")

        dict_actions = random.choice([True, False])

        actions = {} if dict_actions else []
        for agent in env.agents:
            obs = {
                "obs": obs_dict[agent.name] #Observation of a single agent
            }

            if not random_action and trainer is not None:
                #action = trainer.compute_actions(observations=obs)
                action, state_out, actions_info = trainer.get_policy().compute_actions_from_input_dict(input_dict=obs)
                action = action[0].reshape(-1, 1) #Get colums vector from row vector
            else:
                action = _get_deterministic_action(agent, env.continuous_actions, env)
            if dict_actions:
                actions.update({agent.name: action})
            else:
                actions.append(action)

        obs_dict, rews, dones, info = env.step(actions)

        print(rews)

        if render:
            frame = env.render(
                mode="rgb_array",
                agent_index_focus=None,  # Can give the camera an agent index to focus on
                visualize_when_rgb=visualize_render,
            )
            if save_render:
                frame_list.append(frame)

    total_time = time.time() - init_time
    print(
        f"It took: {total_time}s for {n_steps} steps of {env.num_envs} parallel environments on device {env.device} "
        f"for {env_config['scenario_name']} scenario."
    )

    if render and save_render:
        save_video(scenario_name, frame_list, fps=1 / env.scenario.world.dt)


if __name__ == "__main__":
    use_vmas_env(
        render=True,
        save_render=False,
        random_action=False,
        env_config={
                "device": "cpu",
                "num_envs": 1,
                "scenario_name": "try_custom_scenario",
                "continuous_actions": False,
                "max_steps": 100,
                "scenario_config": {
                    "n_agents": 9,
                },
            }
    )